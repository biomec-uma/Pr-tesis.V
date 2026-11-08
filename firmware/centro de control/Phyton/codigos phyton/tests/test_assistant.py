"""Asistente IA: validación de propuestas y bucle de herramientas con un cliente falso (sin red)."""

import json
import unittest
from types import SimpleNamespace as NS

from biomec.core.assistant import (
    EFFORT, FALLBACK_BETA, MODEL, Assistant, AssistantError, Callbacks, build_system_prompt, validate_proposal,
)
from biomec.core.commands import CommandCatalog
from biomec.paths import config_file


class FakeStream:
    def __init__(self, events, final):
        self.events, self.final = events, final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for e in self.events:
            if isinstance(e, Exception):
                raise e
            yield e

    def get_final_message(self):
        return self.final


class FakeClient:
    def __init__(self, streams):
        self.streams = list(streams)
        self.calls = []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        item = self.streams.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def text_turn(text):
    return FakeStream([NS(type="text", text=text)], NS(stop_reason="end_turn", content=[NS(type="text", text=text)]))


def tool_turn(tool_id, name, args):
    block = NS(type="tool_use", id=tool_id, name=name, input=args)
    start = NS(type="content_block_start", content_block=NS(type="tool_use", name=name))
    return FakeStream([start], NS(stop_reason="tool_use", content=[block]))


class Recorder(Callbacks):
    def __init__(self):
        self.text, self.activity, self.proposals = [], [], []

    def on_text(self, delta):
        self.text.append(delta)

    def on_activity(self, text):
        self.activity.append(text)

    def on_proposal(self, proposal):
        self.proposals.append(proposal)


class AssistantTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = CommandCatalog(config_file("commands.json"))

    def make(self, streams, state=None):
        a = Assistant(self.cat, lambda: state or {"conexion": "simulación", "gesto_activo": "6 · Señalar"})
        a._client = FakeClient(streams)
        return a

    def test_system_prompt_has_catalog(self):
        prompt = build_system_prompt(self.cat)
        self.assertIn("POSTURA <A|C|->", prompt)
        self.assertIn("@", prompt)
        self.assertIn("Gancho", prompt)

    def test_validate(self):
        p, problem = validate_proposal({"explicacion": "Pinza", "pasos": [
            {"comando": "postura c a a 90", "espera_ms": 3000}, {"comando": "ABRIR"}]}, self.cat)
        self.assertEqual(problem, "")
        self.assertEqual(p.steps, [("POSTURA c a a 90", 3000), ("ABRIR", 0)])
        for bad in ({}, {"explicacion": "x", "pasos": []}, {"explicacion": "x", "pasos": [{"comando": "VOLAR"}]},
                    {"explicacion": "x", "pasos": [{"comando": "GESTO 3", "espera_ms": 99999}]},
                    {"explicacion": "x", "pasos": [{"comando": "GESTO 3", "espera_ms": True}]}, "texto"):
            self.assertIsNone(validate_proposal(bad, self.cat)[0], bad)

    def test_text_turn(self):
        a = self.make([text_turn("Hola")])
        rec = Recorder()
        self.assertEqual(a.run_turn("hola", rec), "ok")
        self.assertEqual("".join(rec.text), "Hola")
        self.assertEqual([m["role"] for m in a.messages], ["user", "assistant"])
        call = a._client.calls[0]
        self.assertEqual(call["model"], MODEL)
        self.assertEqual(call["output_config"], {"effort": EFFORT})
        self.assertEqual(call["fallbacks"], "default")
        self.assertIn(FALLBACK_BETA, call["betas"])
        self.assertEqual(call["cache_control"], {"type": "ephemeral"})
        self.assertTrue(all(t["eager_input_streaming"] for t in call["tools"]))

    def test_tools_then_answer(self):
        a = self.make([
            tool_turn("t1", "leer_estado", {}),
            tool_turn("t2", "proponer_comandos", {"explicacion": "Señalar", "pasos": [{"comando": "GESTO 6"}]}),
            text_turn("Te propongo señalar."),
        ])
        rec = Recorder()
        self.assertEqual(a.run_turn("señala", rec), "ok")
        self.assertEqual(len(rec.proposals), 1)
        self.assertEqual(rec.proposals[0].steps, [("GESTO 6", 0)])
        roles = [m["role"] for m in a.messages]
        self.assertEqual(roles, ["user", "assistant", "user", "assistant", "user", "assistant"])
        state = json.loads(a.messages[2]["content"][0]["content"])
        self.assertEqual(state["gesto_activo"], "6 · Señalar")
        self.assertIn("NO se ha ejecutado", a.messages[4]["content"][0]["content"])
        self.assertEqual(len(rec.activity), 2)

    def test_invalid_proposal_goes_back_as_error(self):
        a = self.make([tool_turn("t1", "proponer_comandos", {"explicacion": "x", "pasos": [{"comando": "VOLAR"}]}),
                       text_turn("Perdona, ese comando no existe.")])
        rec = Recorder()
        a.run_turn("vuela", rec)
        result = a.messages[2]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("VOLAR", result["content"])
        self.assertEqual(rec.proposals, [])

    def test_error_rolls_back_turn(self):
        import anthropic
        a = self.make([text_turn("primera"), tool_turn("t1", "leer_estado", {}),
                       anthropic.APIConnectionError(request=NS(method="POST", url="https://api"))])
        a.run_turn("uno", Recorder())
        with self.assertRaises(AssistantError):
            a.run_turn("dos", Recorder())
        self.assertEqual([m["role"] for m in a.messages], ["user", "assistant"])  # el turno fallido no queda

    def test_refusal_and_cancel(self):
        refused = FakeStream([], NS(stop_reason="refusal", content=[]))
        a = self.make([refused])
        self.assertEqual(a.run_turn("algo", Recorder()), "refusal")
        self.assertEqual(a.messages, [])
        b = self.make([FakeStream([NS(type="text", text="a"), NS(type="text", text="b")], None)])

        class Cancel(Recorder):
            def on_text(self, delta):
                b.cancel.set()
        self.assertEqual(b.run_turn("algo", Cancel()), "cancelled")
        self.assertEqual(b.messages, [])

    def test_missing_credentials(self):
        a = self.make([TypeError("Could not resolve authentication method. Expected one of api_key...")])
        with self.assertRaises(AssistantError) as ctx:
            a.run_turn("hola", Recorder())
        self.assertIn("clave", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
