<div align="center">

# BIOMEC UMA

### Prótesis de mano mioeléctrica de bajo coste

*Leer la intención del músculo y convertirla en movimiento.*

![ESP32](https://img.shields.io/badge/ESP32-C3%20%7C%20C6-E7352C?logo=espressif&logoColor=white)
![PlatformIO](https://img.shields.io/badge/PlatformIO-Arduino-F5822A?logo=platformio&logoColor=white)
![EMG](https://img.shields.io/badge/EMG-ADS1198-0A7BBB)
![Estado](https://img.shields.io/badge/estado-en%20desarrollo-yellow)

</div>

---

## Sobre el proyecto

**BIOMEC** es un proyecto de la **Universidad de Málaga** que diseña una prótesis
de mano controlada por la actividad eléctrica de los músculos del usuario.

Cuando un músculo se contrae genera pequeñas señales eléctricas, del orden de
microvoltios, que pueden medirse sobre la piel. La prótesis capta esas señales,
interpreta qué quiere hacer la persona y mueve los dedos en consecuencia. Todo ello
con componentes accesibles y de forma abierta.

## Cómo funciona

```text
   Músculo  ──►  Captación  ──►  Procesado  ──►  Movimiento
 (señal EMG)     (ADS1198)        (ESP32)        (motores)
```

1. **Captación.** Unos electrodos sobre el antebrazo recogen la señal muscular y un
   conversor de precisión (ADS1198) la digitaliza.
2. **Comunicación.** Un microcontrolador ESP32 envía los datos sin cables a la
   unidad principal.
3. **Interpretación.** La señal se analiza para reconocer la intención del usuario.
4. **Acción.** Los motores mueven los dedos de la mano.

## Qué hay en este repositorio

Este repositorio reúne la parte de **hardware y software** de la prótesis:

| Carpeta | Contenido |
| --- | --- |
| `firmware/EMG` | Adquisición de la señal muscular y su librería |
| `firmware/maestro` | Unidad principal que recibe los datos |
| `firmware/motor` | Control de los motores de la mano |

Cada módulo incluye su propia documentación para ponerlo en marcha.

## Estado

🟢 Adquisición de la señal EMG
🟢 Comunicación inalámbrica entre placas
🟡 Análisis y tratamiento de la señal
⚪ Control de motores
⚪ Integración en la mano

## Equipo

Proyecto desarrollado por el equipo **BIOMEC** de la Universidad de Málaga.

---

<div align="center">
<sub>BIOMEC UMA · Ingeniería al servicio de las personas</sub>
</div>
