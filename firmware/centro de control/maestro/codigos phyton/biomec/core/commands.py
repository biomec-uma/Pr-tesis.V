"""Catálogo de comandos: se carga desde config/commands.json.

La app nunca tiene comandos escritos en el código: añadir, quitar o cambiar
un comando es editar el JSON. Este módulo valida lo que escribe el usuario y
construye la línea exacta que se envía a la ESP32.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

BRIDGE_PREFIX = "@"


@dataclass
class Argument:
    name: str
    type: str = "text"  # int | float | text
    min: float | None = None
    max: float | None = None
    choices: list[str] | None = None  # valores permitidos (texto), p. ej. ["ABRIR", "CERRAR"]

    def validate(self, raw: str) -> str | None:
        """Devuelve un mensaje de error, o None si el valor es correcto."""
        if self.choices and raw.upper() not in (c.upper() for c in self.choices):
            return f"'{self.name}' debe ser uno de: {', '.join(self.choices)}"
        if self.type in ("int", "float"):
            try:
                value = int(raw) if self.type == "int" else float(raw)
            except ValueError:
                return f"'{self.name}' debe ser {'un entero' if self.type == 'int' else 'un número'} (recibido '{raw}')"
            if self.min is not None and value < self.min:
                return f"'{self.name}' debe ser ≥ {self.min:g}"
            if self.max is not None and value > self.max:
                return f"'{self.name}' debe ser ≤ {self.max:g}"
        return None


@dataclass
class Command:
    name: str
    description: str = ""
    category: str = "General"
    target: str = "mano"  # mano | puente
    args: list[Argument] = field(default_factory=list)

    @property
    def usage(self) -> str:
        return " ".join([self.name] + [f"<{'|'.join(a.choices)}>" if a.choices else f"<{a.name}>" for a in self.args])

    def wire_line(self, args: list[str]) -> str:
        """Línea que se envía por USB al puente."""
        prefix = BRIDGE_PREFIX if self.target == "puente" else ""
        args = [a.upper() if spec.choices else a for spec, a in zip(self.args, args)]
        return " ".join([prefix + self.name, *args])


class CommandError(ValueError):
    pass


class CommandCatalog:
    def __init__(self, path: Path):
        self.path = path
        self.commands: dict[str, Command] = {}
        self.reload()

    def reload(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.commands = {}
        for item in data.get("commands", []):
            args = [Argument(**a) for a in item.get("args", [])]
            cmd = Command(
                name=item["name"].upper(),
                description=item.get("description", ""),
                category=item.get("category", "General"),
                target=item.get("target", "mano"),
                args=args,
            )
            self.commands[cmd.name] = cmd

    def __iter__(self):
        return iter(self.commands.values())

    def names(self) -> list[str]:
        return list(self.commands)

    def get(self, name: str) -> Command | None:
        return self.commands.get(name.upper())

    def build(self, text: str) -> tuple[Command, str]:
        """Valida el texto escrito por el usuario y devuelve (comando, línea a enviar).

        Lanza CommandError con un mensaje legible si algo no cuadra.
        """
        parts = text.strip().split()
        if not parts:
            raise CommandError("Comando vacío.")
        name = parts[0].upper().lstrip(BRIDGE_PREFIX)
        cmd = self.get(name)
        if cmd is None:
            raise CommandError(f"Comando desconocido: {name}. Consulta la pestaña Comandos.")
        args = parts[1:]
        if len(args) != len(cmd.args):
            raise CommandError(f"{cmd.name} espera {len(cmd.args)} argumento(s). Uso: {cmd.usage}")
        for spec, raw in zip(cmd.args, args):
            problem = spec.validate(raw)
            if problem:
                raise CommandError(f"{cmd.name}: {problem}. Uso: {cmd.usage}")
        return cmd, cmd.wire_line(args)
