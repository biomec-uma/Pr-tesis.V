#ifndef BIOMEC_ADS119X_H
#define BIOMEC_ADS119X_H

#include "Arduino.h"
#include "SPI.h"

#define ADS119X_TOTAL_CH   8   
#define ADS119X_BYTES_PER_CH   2   

//-------------Comandos (10 en total)
//    Comandos de sistema
#define  ADS119X_CMD_WAKEUP    0x02    // Despertar del modo standby. NOP en modo normal.
#define  ADS119X_CMD_STANDBY   0x04    // Entrar en modo standby. Reduce el consumo.
#define  ADS119X_CMD_RESET     0x06    // Resetear todos los registros a valores por defecto.
#define  ADS119X_CMD_START     0x08    // Iniciar o reiniciar conversiones.
#define  ADS119X_CMD_STOP      0x0A    // Detener conversiones.
//    Comandos de lectura de datos
#define  ADS119X_CMD_RDATAC    0x10    // Activar modo lectura continua (por defecto al encender). RREG ignorado en este modo.
#define  ADS119X_CMD_SDATAC    0x11    // Detener modo lectura continua. Necesario antes de RREG/WREG.
#define  ADS119X_CMD_RDATA     0x12    // Leer dato por comando. Soporta lecturas múltiples.
//    Comandos de lectura/escritura de registros
#define  ADS119X_CMD_RREG      0x20    // Leer n registros desde dirección r: 001r rrrr 000n nnnn.
#define  ADS119X_CMD_WREG      0x40    // Escribir n registros desde dirección r: 010r rrrr 000n nnnn.
                
//    * When in RDATAC mode, the RREG command is ignored.           
//    "**  n nnnn = number of registers to be read/written – 1. For example, to read/write three registers, set nnnn = 0 (0010). rrrr = starting register address for read/write opcodes."           

//-------- Direcciones de registros (26 en total)
#define  ADS119X_REG_SIZE    0x1A    // Número total de registros del dispositivo.
//    Configuración del dispositivo (solo lectura)
#define  ADS119X_ADD_ID    0x00    // Registro de identificación del dispositivo.
//    Configuración global
#define  ADS119X_ADD_CONFIG1   0x01    // Registro de configuración 1: tasa de muestreo, daisy-chain, reloj.
#define  ADS119X_ADD_CONFIG2   0x02    // Registro de configuración 2: señal de test interna/externa, amplitud y frecuencia.
#define  ADS119X_ADD_CONFIG3   0x03    // Registro de configuración 3: referencia interna, RLD.
#define  ADS119X_ADD_LOFF      0x04    // Registro de detección de lead-off: umbral, corriente y frecuencia.
//    Configuración por canal
#define  ADS119X_ADD_CH1SET    0x05    // Configuración canal 1: power-down, ganancia PGA, multiplexor.
#define  ADS119X_ADD_CH2SET    0x06    // Configuración canal 2: power-down, ganancia PGA, multiplexor.
#define  ADS119X_ADD_CH3SET    0x07    // Configuración canal 3: power-down, ganancia PGA, multiplexor.
#define  ADS119X_ADD_CH4SET    0x08    // Configuración canal 4: power-down, ganancia PGA, multiplexor.
#define  ADS119X_ADD_CH5SET    0x09    // Configuración canal 5: power-down, ganancia PGA, multiplexor. (solo ADS1196/8)
#define  ADS119X_ADD_CH6SET    0x0A    // Configuración canal 6: power-down, ganancia PGA, multiplexor. (solo ADS1196/8)
#define  ADS119X_ADD_CH7SET    0x0B    // Configuración canal 7: power-down, ganancia PGA, multiplexor. (solo ADS1198)
#define  ADS119X_ADD_CH8SET    0x0C    // Configuración canal 8: power-down, ganancia PGA, multiplexor. (solo ADS1198)
#define  ADS119X_ADD_RLD_SENSP 0x0D    // Selección de canales positivos para RLD.
#define  ADS119X_ADD_RLD_SENSN 0x0E    // Selección de canales negativos para RLD.
#define  ADS119X_ADD_LOFF_SENSP  0x0F  // Habilitación de detección de lead-off en entradas positivas.
#define  ADS119X_ADD_LOFF_SENSN  0x10  // Habilitación de detección de lead-off en entradas negativas.
#define  ADS119X_ADD_LOFF_FLIP   0x11  // Inversión de corriente de lead-off por canal.
//    Registros de estado de lead-off (solo lectura)
#define  ADS119X_ADD_LOFF_STATP  0x12  // Estado de lead-off en entradas positivas: 0=conectado, 1=desconectado.
#define  ADS119X_ADD_LOFF_STATN  0x13  // Estado de lead-off en entradas negativas: 0=conectado, 1=desconectado.
//    GPIO y otros registros
#define  ADS119X_ADD_GPIO      0x14    // Registro GPIO: control y datos de pines de propósito general.
#define  ADS119X_ADD_PACE      0x15    // Registro PACE: detección de marcapasos.
#define  ADS119X_ADD_RESERVED  0x16    // Reservado. No modificar.
#define  ADS119X_ADD_CONFIG4   0x17    // Registro de configuración 4: modo single-shot, WCT, lead-off continuo.
#define  ADS119X_ADD_WCT1      0x18    // Registro WCT1: configuración del circuito de Wilson Central Terminal.
#define  ADS119X_ADD_WCT2      0x19    // Registro WCT2: configuración del circuito de Wilson Central Terminal.

//-------- Constantes de identificación del dispositivo (solo lectura)
#define ADS119X_ID_7_2           0xB4    // Bits [7:2] fijos del registro ID: 101x xxxx familia ADS119X, xxx1 01xx constante.
#define ADS119X_DEV_CH_ID_MASK   0x03    // Máscara bits [1:0] del ID: identificador del número de canales.
#define ADS119X_DEV_ID_ADS1194   0x00    // ID = 00: dispositivo ADS1194 (4 canales).
#define ADS119X_DEV_ID_ADS1196   0x01    // ID = 01: dispositivo ADS1196 (6 canales).
#define ADS119X_DEV_ID_ADS1198   0x02    // ID = 10: dispositivo ADS1198 (8 canales).

//-------- CONFIG1: Registro de configuración 1
#define ADS119X_DAISY_MASK    0x40    // Máscara bit DAISY_EN.
#define ADS119X_DAISY_ENABLE  0x00    // DAISY_EN=0: modo daisy-chain (por defecto).
#define ADS119X_DAISY_DISABLE 0x40    // DAISY_EN=1: modo lectura múltiple.

#define ADS119X_CLK_MASK      0x20    // Máscara bit CLK_EN.
#define ADS119X_CLK_DISABLE   0x00    // CLK_EN=0: salida de reloj interno desactivada (por defecto).
#define ADS119X_CLK_ENABLE    0x20    // CLK_EN=1: salida de reloj interno activada. Consume energía adicional.

#define ADS119X_DRATE_MASK    0x07    // Máscara bits DR[2:0]: tasa de muestreo.
#define ADS119X_DRATE_8000SPS 0x00    // DR=000: 8000 SPS (f_MOD/16).
#define ADS119X_DRATE_4000SPS 0x01    // DR=001: 4000 SPS (f_MOD/32).
#define ADS119X_DRATE_2000SPS 0x02    // DR=010: 2000 SPS (f_MOD/64).
#define ADS119X_DRATE_1000SPS 0x03    // DR=011: 1000 SPS (f_MOD/128).
#define ADS119X_DRATE_500SPS  0x04    // DR=100: 500 SPS (f_MOD/256). Por defecto.
#define ADS119X_DRATE_250SPS  0x05    // DR=101: 250 SPS (f_MOD/512).
#define ADS119X_DRATE_125SPS  0x06    // DR=110: 125 SPS (f_MOD/1024).

//-------- CONFIG2: Registro de configuración 2
#define ADS119X_INT_TEST_MASK   0x10    // Máscara bit INT_TEST: fuente de señal de test.
#define ADS119X_EXT_TEST        0x00    // INT_TEST=0: señal de test generada externamente (por defecto).
#define ADS119X_INT_TEST        0x10    // INT_TEST=1: señal de test generada internamente.

#define ADS119X_TEST_AMP_MASK   0x04    // Máscara bit TEST_AMP: amplitud de señal de calibración.
#define ADS119X_TEST_AMP_X1     0x00    // TEST_AMP=0: amplitud -1 x (VREFP-VREFN)/2.4mV (por defecto).
#define ADS119X_TEST_AMP_X2     0x04    // TEST_AMP=1: amplitud -2 x (VREFP-VREFN)/2.4mV.

#define ADS119X_TEST_FREQ_MASK  0x03    // Máscara bits TEST_FREQ[1:0]: frecuencia de señal de calibración.
#define ADS119X_TEST_FREQ_21    0x00    // TEST_FREQ=00: onda cuadrada a f_CLK/2^21 (por defecto).
#define ADS119X_TEST_FREQ_20    0x01    // TEST_FREQ=01: onda cuadrada a f_CLK/2^20.
#define ADS119X_TEST_FREQ_DC    0x03    // TEST_FREQ=11: señal DC.

//-------- CONFIG3: Registro de configuración 3
#define ADS119X_REFBUF_MASK            0x80    // Máscara bit PD_REFBUF: buffer de referencia interna.
#define ADS119X_REFBUF_DISABLE         0x00    // PD_REFBUF=0: buffer de referencia desactivado (por defecto).
#define ADS119X_REFBUF_ENABLE          0x80    // PD_REFBUF=1: buffer de referencia activado. Esperar 150ms tras activar.

#define ADS119X_VREF_4V_MASK           0x20    // Máscara bit VREF_4V: tensión de referencia interna.
#define ADS119X_VREF_2V4               0x00    // VREF_4V=0: referencia 2.4V (por defecto).
#define ADS119X_VREF_4V                0x20    // VREF_4V=1: referencia 4V (solo con AVDD >= 4.5V).

#define ADS119X_RLD_MEAS_MASK          0x10    // Máscara bit RLD_MEAS: medida de la señal RLD.
#define ADS119X_RLD_MEAS_DISABLE       0x00    // RLD_MEAS=0: medida RLD desactivada (por defecto).
#define ADS119X_RLD_MEAS_ENABLE        0x10    // RLD_MEAS=1: señal RLD enrutada al multiplexor del canal.

#define ADS119X_RLDREF_INT_MASK        0x08    // Máscara bit RLDREF_INT: fuente de referencia RLD.
#define ADS119X_RLDREF_EXT             0x00    // RLDREF_INT=0: referencia RLD externa (por defecto).
#define ADS119X_RLDREF_INT             0x08    // RLDREF_INT=1: referencia RLD interna (AVDD-AVSS)/2.

#define ADS119X_NOT_PD_RLD_MASK        0x04    // Máscara bit PD_RLD: amplificador RLD.
#define ADS119X_PD_RLD_MASK            ADS119X_NOT_PD_RLD_MASK   // Alias nombre datasheet
#define ADS119X_RLD_AMP_DISABLE        0x00    // PD_RLD=0: amplificador RLD desactivado (por defecto).
#define ADS119X_RLD_AMP_ENABLE         0x04    // PD_RLD=1: amplificador RLD activado.

#define ADS119X_RLD_LOFF_SENS_MASK     0x02    // Máscara bit RLD_LOFF_SENS: detección de lead-off en RLD.
#define ADS119X_RLD_LOFF_SENS_DISABLE  0x00    // RLD_LOFF_SENS=0: desactivado (por defecto).
#define ADS119X_RLD_LOFF_SENS_ENABLE   0x02    // RLD_LOFF_SENS=1: activado.

#define ADS119X_RLD_STAT_MASK          0x01    // Máscara bit RLD_STAT: estado del amplificador RLD (solo lectura).
#define ADS119X_RLD_STAT_CONNECTED     0x00    // RLD_STAT=0: RLD conectado.
#define ADS119X_RLD_STAT_LOFF          0x01    // RLD_STAT=1: RLD desconectado (lead-off detectado).

//-------- LOFF: Registro de control de detección de lead-off
#define ADS119X_COMP_TH_MASK      0xE0    // Máscara bits COMP_TH[2:0]: umbral del comparador de lead-off.
#define ADS119X_COMP_TH_0         0x00    // COMP_TH=000: positivo 95% / negativo 5% (por defecto).
#define ADS119X_COMP_TH_1         0x20    // COMP_TH=001: positivo 92.5% / negativo 7.5%.
#define ADS119X_COMP_TH_2         0x40    // COMP_TH=010: positivo 90% / negativo 10%.
#define ADS119X_COMP_TH_3         0x60    // COMP_TH=011: positivo 87.5% / negativo 12.5%.
#define ADS119X_COMP_TH_4         0x80    // COMP_TH=100: positivo 85% / negativo 15%.
#define ADS119X_COMP_TH_5         0xA0    // COMP_TH=101: positivo 80% / negativo 20%.
#define ADS119X_COMP_TH_6         0xC0    // COMP_TH=110: positivo 75% / negativo 25%.
#define ADS119X_COMP_TH_7         0xE0    // COMP_TH=111: positivo 70% / negativo 30%.

#define ADS119X_VLEAD_OFF_MASK    0x10    // Máscara bit VLEAD_OFF_EN: 0=detección por corriente (por defecto), 1=detección por resistencia pull-up/pull-down.
#define ADS119X_VLEAD_OFF_CURRENT 0x00    // VLEAD_OFF_EN=0: detección por corriente (por defecto).
#define ADS119X_VLEAD_OFF_RESIST  0x10    // VLEAD_OFF_EN=1: detección por resistencia pull-up/pull-down.

#define ADS119X_ILEAD_OFF_MASK    0x0C    // Máscara bits ILEAD_OFF[1:0]: magnitud de corriente de lead-off.
#define ADS119X_ILEAD_OFF_4NA     0x00    // ILEAD_OFF=00: 4nA (por defecto).
#define ADS119X_ILEAD_OFF_8NA     0x04    // ILEAD_OFF=01: 8nA.
#define ADS119X_ILEAD_OFF_12NA    0x08    // ILEAD_OFF=10: 12nA.
#define ADS119X_ILEAD_OFF_16NA    0x0C    // ILEAD_OFF=11: 16nA.

#define ADS119X_FLEAD_OFF_MASK    0x03    // Máscara bits FLEAD_OFF[1:0]: frecuencia de detección de lead-off.
#define ADS119X_FLEAD_OFF_AC      0x01    // FLEAD_OFF=01: detección AC a f_DR/4.
#define ADS119X_FLEAD_OFF_DC      0x03    // FLEAD_OFF=11: detección DC.

//-------- CHnSET: Configuración por canal
#define ADS119X_CHnSET_PD_NORMAL      0x00    // PD=0: canal en modo normal (por defecto).
#define ADS119X_CHnSET_PD_POWERDOWN   0x80    // PD=1: canal en power-down. Recomendado configurar MUX en corto.
#define ADS119X_CHnSET_PD_MASK        0x80    // Máscara bit PD: power-down del canal.

#define ADS119X_CHnSET_GAIN_MASK      0x70    // Máscara bits GAIN[2:0]: ganancia del PGA.
#define ADS119X_CHnSET_GAIN_6         0x00    // GAIN=000: ganancia 6 (por defecto).
#define ADS119X_CHnSET_GAIN_1         0x10    // GAIN=001: ganancia 1.
#define ADS119X_CHnSET_GAIN_2         0x20    // GAIN=010: ganancia 2.
#define ADS119X_CHnSET_GAIN_3         0x30    // GAIN=011: ganancia 3.
#define ADS119X_CHnSET_GAIN_4         0x40    // GAIN=100: ganancia 4.
#define ADS119X_CHnSET_GAIN_8         0x50    // GAIN=101: ganancia 8.
#define ADS119X_CHnSET_GAIN_12        0x60    // GAIN=110: ganancia 12.

#define ADS119X_CHnSET_MUX_MASK       0x07    // Máscara bits MUX[2:0]: selección de entrada del canal.
#define ADS119X_CHnSET_MUX_NORMAL     0x00    // MUX=000: entrada normal desde electrodos (por defecto).
#define ADS119X_CHnSET_MUX_IN_SHORT   0x01    // MUX=001: entradas en corto a (AVDD-AVSS)/2. Usado para medida de ruido.
#define ADS119X_CHnSET_MUX_RLD_MEAS   0x02    // MUX=010: medida de señal RLD.
#define ADS119X_CHnSET_MUX_MVDD       0x03    // MUX=011: medida de tensión de alimentación (MVDD).
#define ADS119X_CHnSET_MUX_TEMP       0x04    // MUX=100: sensor de temperatura interno.
#define ADS119X_CHnSET_MUX_TEST       0x05    // MUX=101: señal de test interna.
#define ADS119X_CHnSET_MUX_RLD_DRP    0x06    // MUX=110: entrada positiva conectada a RLD.
#define ADS119X_CHnSET_MUX_RLD_DRN    0x07    // MUX=111: entrada negativa conectada a RLD.

//-------- RLD_SENSP: Selección de entradas positivas de cada canal para la derivación de la señal RLD.
// Cada bit habilita la entrada positiva del canal correspondiente. Varios canales pueden activarse simultáneamente.
#define ADS119X_RLD_SENSP_CH1    0x01    // Bit 0: canal 1 positivo conectado al derivador RLD.
#define ADS119X_RLD_SENSP_CH2    0x02    // Bit 1: canal 2 positivo conectado al derivador RLD.
#define ADS119X_RLD_SENSP_CH3    0x04    // Bit 2: canal 3 positivo conectado al derivador RLD.
#define ADS119X_RLD_SENSP_CH4    0x08    // Bit 3: canal 4 positivo conectado al derivador RLD.
#define ADS119X_RLD_SENSP_CH5    0x10    // Bit 4: canal 5 positivo conectado al derivador RLD. No disponible en ADS1194.
#define ADS119X_RLD_SENSP_CH6    0x20    // Bit 5: canal 6 positivo conectado al derivador RLD. No disponible en ADS1194.
#define ADS119X_RLD_SENSP_CH7    0x40    // Bit 6: canal 7 positivo conectado al derivador RLD. No disponible en ADS1194/6.
#define ADS119X_RLD_SENSP_CH8    0x80    // Bit 7: canal 8 positivo conectado al derivador RLD. No disponible en ADS1194/6.

//-------- RLD_SENSN: Selección de entradas negativas de cada canal para la derivación de la señal RLD.
// Cada bit habilita la entrada negativa del canal correspondiente. Varios canales pueden activarse simultáneamente.
#define ADS119X_RLD_SENSN_CH1    0x01    // Bit 0: canal 1 negativo conectado al derivador RLD.
#define ADS119X_RLD_SENSN_CH2    0x02    // Bit 1: canal 2 negativo conectado al derivador RLD.
#define ADS119X_RLD_SENSN_CH3    0x04    // Bit 2: canal 3 negativo conectado al derivador RLD.
#define ADS119X_RLD_SENSN_CH4    0x08    // Bit 3: canal 4 negativo conectado al derivador RLD.
#define ADS119X_RLD_SENSN_CH5    0x10    // Bit 4: canal 5 negativo conectado al derivador RLD. No disponible en ADS1194.
#define ADS119X_RLD_SENSN_CH6    0x20    // Bit 5: canal 6 negativo conectado al derivador RLD. No disponible en ADS1194.
#define ADS119X_RLD_SENSN_CH7    0x40    // Bit 6: canal 7 negativo conectado al derivador RLD. No disponible en ADS1194/6.
#define ADS119X_RLD_SENSN_CH8    0x80    // Bit 7: canal 8 negativo conectado al derivador RLD. No disponible en ADS1194/6.

//-------- LOFF_SENSP: Habilitación de detección de lead-off en entradas positivas de cada canal.
// Los bits de LOFF_STATP solo son válidos si el bit correspondiente de este registro está a '1'.
#define ADS119X_LOFF_SENSP_CH1    0x01    // Bit 0: detección lead-off habilitada en canal 1 positivo.
#define ADS119X_LOFF_SENSP_CH2    0x02    // Bit 1: detección lead-off habilitada en canal 2 positivo.
#define ADS119X_LOFF_SENSP_CH3    0x04    // Bit 2: detección lead-off habilitada en canal 3 positivo.
#define ADS119X_LOFF_SENSP_CH4    0x08    // Bit 3: detección lead-off habilitada en canal 4 positivo.
#define ADS119X_LOFF_SENSP_CH5    0x10    // Bit 4: detección lead-off habilitada en canal 5 positivo. No disponible en ADS1194.
#define ADS119X_LOFF_SENSP_CH6    0x20    // Bit 5: detección lead-off habilitada en canal 6 positivo. No disponible en ADS1194.
#define ADS119X_LOFF_SENSP_CH7    0x40    // Bit 6: detección lead-off habilitada en canal 7 positivo. No disponible en ADS1194/6.
#define ADS119X_LOFF_SENSP_CH8    0x80    // Bit 7: detección lead-off habilitada en canal 8 positivo. No disponible en ADS1194/6.

//-------- LOFF_SENSN: Habilitación de detección de lead-off en entradas negativas de cada canal.
// Los bits de LOFF_STATN solo son válidos si el bit correspondiente de este registro está a '1'.
#define ADS119X_LOFF_SENSN_CH1    0x01    // Bit 0: detección lead-off habilitada en canal 1 negativo.
#define ADS119X_LOFF_SENSN_CH2    0x02    // Bit 1: detección lead-off habilitada en canal 2 negativo.
#define ADS119X_LOFF_SENSN_CH3    0x04    // Bit 2: detección lead-off habilitada en canal 3 negativo.
#define ADS119X_LOFF_SENSN_CH4    0x08    // Bit 3: detección lead-off habilitada en canal 4 negativo.
#define ADS119X_LOFF_SENSN_CH5    0x10    // Bit 4: detección lead-off habilitada en canal 5 negativo. No disponible en ADS1194.
#define ADS119X_LOFF_SENSN_CH6    0x20    // Bit 5: detección lead-off habilitada en canal 6 negativo. No disponible en ADS1194.
#define ADS119X_LOFF_SENSN_CH7    0x40    // Bit 6: detección lead-off habilitada en canal 7 negativo. No disponible en ADS1194/6.
#define ADS119X_LOFF_SENSN_CH8    0x80    // Bit 7: detección lead-off habilitada en canal 8 negativo. No disponible en ADS1194/6.

//-------- LOFF_FLIP: Inversión de la dirección de corriente de lead-off por canal.
// Cuando un bit está a '1', intercambia la corriente de pull-up y pull-down del canal correspondiente.
#define ADS119X_LOFF_FLIP_CH1    0x01    // Bit 0: inversión de corriente lead-off en canal 1.
#define ADS119X_LOFF_FLIP_CH2    0x02    // Bit 1: inversión de corriente lead-off en canal 2.
#define ADS119X_LOFF_FLIP_CH3    0x04    // Bit 2: inversión de corriente lead-off en canal 3.
#define ADS119X_LOFF_FLIP_CH4    0x08    // Bit 3: inversión de corriente lead-off en canal 4.
#define ADS119X_LOFF_FLIP_CH5    0x10    // Bit 4: inversión de corriente lead-off en canal 5. No disponible en ADS1194.
#define ADS119X_LOFF_FLIP_CH6    0x20    // Bit 5: inversión de corriente lead-off en canal 6. No disponible en ADS1194.
#define ADS119X_LOFF_FLIP_CH7    0x40    // Bit 6: inversión de corriente lead-off en canal 7. No disponible en ADS1194/6.
#define ADS119X_LOFF_FLIP_CH8    0x80    // Bit 7: inversión de corriente lead-off en canal 8. No disponible en ADS1194/6.

//-------- LOFF_STATP: Estado de lead-off en entradas positivas (solo lectura).
// 0=electrodo conectado (lead-on), 1=electrodo desconectado (lead-off).
// Solo válido si el bit correspondiente de LOFF_SENSP está a '1'.
#define ADS119X_LOFF_STATP_CH1    0x01    // Bit 0: estado lead-off canal 1 positivo.
#define ADS119X_LOFF_STATP_CH2    0x02    // Bit 1: estado lead-off canal 2 positivo.
#define ADS119X_LOFF_STATP_CH3    0x04    // Bit 2: estado lead-off canal 3 positivo.
#define ADS119X_LOFF_STATP_CH4    0x08    // Bit 3: estado lead-off canal 4 positivo.
#define ADS119X_LOFF_STATP_CH5    0x10    // Bit 4: estado lead-off canal 5 positivo.
#define ADS119X_LOFF_STATP_CH6    0x20    // Bit 5: estado lead-off canal 6 positivo.
#define ADS119X_LOFF_STATP_CH7    0x40    // Bit 6: estado lead-off canal 7 positivo.
#define ADS119X_LOFF_STATP_CH8    0x80    // Bit 7: estado lead-off canal 8 positivo.

//-------- LOFF_STATN: Estado de lead-off en entradas negativas (solo lectura).
// 0=electrodo conectado (lead-on), 1=electrodo desconectado (lead-off).
// Solo válido si el bit correspondiente de LOFF_SENSN está a '1'.
#define ADS119X_LOFF_STATN_CH1    0x01    // Bit 0: estado lead-off canal 1 negativo.
#define ADS119X_LOFF_STATN_CH2    0x02    // Bit 1: estado lead-off canal 2 negativo.
#define ADS119X_LOFF_STATN_CH3    0x04    // Bit 2: estado lead-off canal 3 negativo.
#define ADS119X_LOFF_STATN_CH4    0x08    // Bit 3: estado lead-off canal 4 negativo.
#define ADS119X_LOFF_STATN_CH5    0x10    // Bit 4: estado lead-off canal 5 negativo.
#define ADS119X_LOFF_STATN_CH6    0x20    // Bit 5: estado lead-off canal 6 negativo.
#define ADS119X_LOFF_STATN_CH7    0x40    // Bit 6: estado lead-off canal 7 negativo.
#define ADS119X_LOFF_STATN_CH8    0x80    // Bit 7: estado lead-off canal 8 negativo.

//-------- GPIO: Registro de propósito general
#define ADS119X_GPIO_DATA_MASK        0xF0    // Máscara bits GPIOD[3:1]: datos de los pines GPIO.
#define ADS119X_GPIO_CONTROL_MASK     0x0F    // Máscara bits GPIOC[3:1]: dirección de los pines GPIO (0=salida, 1=entrada por defecto).

//-------- PACE: Registro de detección de marcapasos
#define ADS119X_PACEE_MASK            0x18    // Máscara bits PACEE[1:0]: selección de canal par para detección de marcapasos.
#define ADS119X_PACEO_MASK            0x06    // Máscara bits PACEO[1:0]: selección de canal impar para detección de marcapasos.
#define ADS119X_NOT_PD_PACE_MASK      0x01    // Máscara bit PD_PACE: 0=detector desactivado, 1=detector activado.
#define ADS119X_PD_PACE_MASK           ADS119X_NOT_PD_PACE_MASK  // Alias nombre datasheet
#define ADS119X_PACE_DETECTOR_DISABLE 0x00    // PD_PACE=0: detector desactivado.
#define ADS119X_PACE_DETECTOR_ENABLE  0x01    // PD_PACE=1: detector activado.

//-------- CONFIG4: Registro de configuración 4
#define ADS119X_SINGLE_SHOT_MASK      0x08    // Máscara bit SINGLE_SHOT: 0=modo continuo (por defecto), 1=conversión única.
#define ADS119X_CONTINUOUS_MODE       0x00    // SINGLE_SHOT=0: modo continuo (por defecto).
#define ADS119X_SINGLE_SHOT_MODE      0x08    // SINGLE_SHOT=1: conversión única.
#define ADS119X_WCT_TO_RLD_MASK       0x04    // Máscara bit WCT_TO_RLD: 0=desactivado (por defecto), 1=salida WCT conectada a RLD.
#define ADS119X_WCT_TO_RLD_DISABLE    0x00    // WCT_TO_RLD=0: desactivado (por defecto).
#define ADS119X_WCT_TO_RLD_ENABLE     0x04    // WCT_TO_RLD=1: salida WCT conectada a RLD.
#define ADS119X_NOT_PD_LOFF_COMP_MASK 0x02    // Máscara bit PD_LOFF_COMP: 0=comparadores lead-off desactivados (por defecto), 1=activados.
#define ADS119X_PD_LOFF_COMP_MASK      ADS119X_NOT_PD_LOFF_COMP_MASK // Alias nombre datasheet
#define ADS119X_LOFF_COMP_DISABLE     0x00    // PD_LOFF_COMP=0: comparadores lead-off desactivados (por defecto).
#define ADS119X_LOFF_COMP_ENABLE      0x02    // PD_LOFF_COMP=1: comparadores lead-off activados.

//-------- WCT1: Registro de control del Terminal de Wilson y derivaciones aumentadas.
#define ADS119X_AVF_CH6_MASK    0x80    // Bit 7: (WCTA+WCTB)/2 a entrada negativa canal 6. Solo ADS1196/8. 0=desactivado (por defecto).
#define ADS119X_AVF_CH6_DISABLE 0x00    // AVF_CH6=0: desactivado (por defecto).
#define ADS119X_AVF_CH6_ENABLE  0x80    // AVF_CH6=1: activado.
#define ADS119X_AVL_CH5_MASK    0x40    // Bit 6: (WCTA+WCTC)/2 a entrada negativa canal 5. Solo ADS1196/8. 0=desactivado (por defecto).
#define ADS119X_AVL_CH5_DISABLE 0x00    // AVL_CH5=0: desactivado (por defecto).
#define ADS119X_AVL_CH5_ENABLE  0x40    // AVL_CH5=1: activado.
#define ADS119X_AVR_CH7_MASK    0x20    // Bit 5: (WCTB+WCTC)/2 a entrada negativa canal 7. Solo ADS1198. 0=desactivado (por defecto).
#define ADS119X_AVR_CH7_DISABLE 0x00    // AVR_CH7=0: desactivado (por defecto).
#define ADS119X_AVR_CH7_ENABLE  0x20    // AVR_CH7=1: activado.
#define ADS119X_AVR_CH4_MASK    0x10    // Bit 4: (WCTB+WCTC)/2 a entrada negativa canal 4. 0=desactivado (por defecto).
#define ADS119X_AVR_CH4_DISABLE 0x00    // AVR_CH4=0: desactivado (por defecto).
#define ADS119X_AVR_CH4_ENABLE  0x10    // AVR_CH4=1: activado.
#define ADS119X_PD_WCTA_MASK    0x08    // Bit 3: PD_WCTA: 0=amplificador WCTA apagado (por defecto), 1=encendido.
#define ADS119X_WCTA_AMP_DISABLE 0x00   // PD_WCTA=0: amplificador WCTA apagado (por defecto).
#define ADS119X_WCTA_AMP_ENABLE  0x08   // PD_WCTA=1: amplificador WCTA encendido.
#define ADS119X_WCTA_MASK       0x07    // Máscara bits WCTA[2:0]: selección de entrada al amplificador WCTA (típicamente electrodo RA).
#define ADS119X_WCTA_CH1P       0x00    // WCTA=000: entrada positiva canal 1 (por defecto).
#define ADS119X_WCTA_CH1N       0x01    // WCTA=001: entrada negativa canal 1.
#define ADS119X_WCTA_CH2P       0x02    // WCTA=010: entrada positiva canal 2.
#define ADS119X_WCTA_CH2N       0x03    // WCTA=011: entrada negativa canal 2.
#define ADS119X_WCTA_CH3P       0x04    // WCTA=100: entrada positiva canal 3.
#define ADS119X_WCTA_CH3N       0x05    // WCTA=101: entrada negativa canal 3.
#define ADS119X_WCTA_CH4P       0x06    // WCTA=110: entrada positiva canal 4.
#define ADS119X_WCTA_CH4N       0x07    // WCTA=111: entrada negativa canal 4.

//-------- WCT2: Registro de control del Terminal de Wilson.
#define ADS119X_PD_WCTC_MASK    0x80    // Bit 7: PD_WCTC: 0=amplificador WCTC apagado (por defecto), 1=encendido.
#define ADS119X_WCTC_AMP_DISABLE 0x00   // PD_WCTC=0: amplificador WCTC apagado (por defecto).
#define ADS119X_WCTC_AMP_ENABLE  0x80   // PD_WCTC=1: amplificador WCTC encendido.
#define ADS119X_PD_WCTB_MASK    0x40    // Bit 6: PD_WCTB: 0=amplificador WCTB apagado (por defecto), 1=encendido.
#define ADS119X_WCTB_AMP_DISABLE 0x00   // PD_WCTB=0: amplificador WCTB apagado (por defecto).
#define ADS119X_WCTB_AMP_ENABLE  0x40   // PD_WCTB=1: amplificador WCTB encendido.
#define ADS119X_WCTB_MASK       0x38    // Máscara bits WCTB[2:0]: selección de entrada al amplificador WCTB (típicamente electrodo LA).
#define ADS119X_WCTB_CH1P       0x00    // WCTB=000: entrada positiva canal 1.
#define ADS119X_WCTB_CH1N       0x08    // WCTB=001: entrada negativa canal 1.
#define ADS119X_WCTB_CH2P       0x10    // WCTB=010: entrada positiva canal 2 (por defecto).
#define ADS119X_WCTB_CH2N       0x18    // WCTB=011: entrada negativa canal 2.
#define ADS119X_WCTB_CH3P       0x20    // WCTB=100: entrada positiva canal 3.
#define ADS119X_WCTB_CH3N       0x28    // WCTB=101: entrada negativa canal 3.
#define ADS119X_WCTB_CH4P       0x30    // WCTB=110: entrada positiva canal 4.
#define ADS119X_WCTB_CH4N       0x38    // WCTB=111: entrada negativa canal 4.
#define ADS119X_WCTC_MASK       0x07    // Máscara bits WCTC[2:0]: selección de entrada al amplificador WCTC (típicamente electrodo LL).
#define ADS119X_WCTC_CH1P       0x00    // WCTC=000: entrada positiva canal 1.
#define ADS119X_WCTC_CH1N       0x01    // WCTC=001: entrada negativa canal 1.
#define ADS119X_WCTC_CH2P       0x02    // WCTC=010: entrada positiva canal 2.
#define ADS119X_WCTC_CH2N       0x03    // WCTC=011: entrada negativa canal 2.
#define ADS119X_WCTC_CH3P       0x04    // WCTC=100: entrada positiva canal 3 (por defecto).
#define ADS119X_WCTC_CH3N       0x05    // WCTC=101: entrada negativa canal 3.
#define ADS119X_WCTC_CH4P       0x06    // WCTC=110: entrada positiva canal 4.
#define ADS119X_WCTC_CH4N       0x07    // WCTC=111: entrada negativa canal 4.



/**
 * @class ADS119X
 * @brief Clase para gestionar la comunicación y control de dispositivos de la familia ADS119X (como el ADS1198) mediante SPI.
 *
 * Permite la adquisición de señales biomédicas multicanal, facilitando la configuración, inicialización y lectura de datos de los canales del ADS119X.
 *
 * Contexto de uso:
 * - Proyectos de adquisición de bioseñales (ECG, EMG, EEG, etc.) en sistemas embebidos, especialmente con microcontroladores compatibles con Arduino.
 * - Soporte para múltiples modelos de la familia ADS119X (1194, 1196, 1198).
 *
 * Características clave:
 * - Métodos para configuración de registros, lectura de datos, pruebas internas y restauración de valores por defecto.
 * - Abstracción de la comunicación SPI y manejo de pines de control.
 * - Facilita la integración en aplicaciones biomédicas portátiles o de laboratorio.
 */
class ADS119X {
 public:
  /**
   * @brief Constructor de la clase ADS119X.
   *
   * Inicializa la instancia y configura los pines necesarios para la comunicación con el ADS119X mediante SPI.
   *
   * @param dataReady_Pin Pin DRDY (Data Ready): Salida digital del ADS119X que indica cuándo hay nuevos datos disponibles (activo en bajo).
   * @param reset_Pin Pin RESET: Entrada digital para reiniciar el dispositivo (activo en bajo).
   * @param cs_Pin Pin CS (Chip Select): Entrada digital para seleccionar el dispositivo en el bus SPI (activo en bajo).
   * @param clk Pin SCLK: Entrada de reloj SPI (Serial Clock).
   * @param miso Pin MISO: Salida de datos SPI del ADS119X (Master In Slave Out).
   * @param mosi Pin MOSI: Entrada de datos SPI al ADS119X (Master Out Slave In).
   *
   * Notas:
   * - Los pines deben conectarse según la tabla de asignación de pines del datasheet del ADS1198.
   * - Es importante respetar los niveles lógicos y la secuencia de inicialización recomendada por el fabricante.
   * - El pin DRDY permite la sincronización eficiente de la lectura de datos.
   * - El pin RESET asegura que el dispositivo pueda ser reiniciado por software o hardware.
   * - El bus SPI debe estar correctamente configurado para operar en modo 1 (CPOL=0, CPHA=1).
   */
  ADS119X(byte dataReady_Pin, byte reset_Pin, byte cs_Pin, byte clk, byte miso, byte mosi); 
  /**
   * @brief Inicializa el ADS119X y la comunicación SPI siguiendo la secuencia de encendido recomendada.
   *
   * Realiza la configuración inicial de los pines, ejecuta la secuencia de power-up (incluyendo retardos y reset por hardware),
   * inicia la comunicación SPI con los parámetros adecuados y verifica la comunicación leyendo el ID del dispositivo.
   *
   * Es imprescindible llamar a este método antes de cualquier otra función de la librería.
   *
   * @return true si la inicialización y la comunicación con el ADS119X son correctas; false si falla la detección del dispositivo.
   *
   * Notas:
   * - Sigue la secuencia de encendido recomendada en el datasheet (power-up sequencing).
   * - Asegura que los retardos mínimos y la gestión de pines cumplen los requisitos del fabricante.
   * - Deja el dispositivo listo para configuración y captura de datos.
   */
  boolean begin();    

  /**
   * @brief Envía un comando SPI al ADS119X.
   *
   * Permite controlar el modo de operación del dispositivo (inicio/parada de conversión, standby, reset, etc.)
   * mediante el envío de comandos definidos en el datasheet.
   *
   * @param cmd Código de comando a enviar (por ejemplo, ADS119X_CMD_START, ADS119X_CMD_STOP, etc.).
   *
   * Notas:
   * - Algunos comandos solo deben usarse en modos específicos (ver datasheet para detalles).
   * - Es recomendable detener la conversión continua (SDATAC) antes de modificar registros.
   * - El uso incorrecto de comandos puede dejar el dispositivo en un estado no deseado.
   */
  void sendCommand(unsigned char cmd);
  /**
   * @brief Escribe uno o varios registros del ADS119X mediante SPI.
   *
   * Envía el comando WREG, que permite modificar el contenido de uno o más registros internos del dispositivo.
   * El comando consta de dos bytes: el primero indica la dirección inicial del registro, y el segundo el número de registros a escribir menos uno, seguido de los datos a escribir.
   *
   * @param address Dirección del registro a escribir (ver mapa de registros en el datasheet).
   * @param value Valor que se escribirá en el registro (si se usa para un solo registro).
   *
   * Notas:
   * - El pin CS debe mantenerse bajo durante toda la operación.
   * - El comando puede usarse en cualquier momento, pero hay restricciones en la velocidad de SCLK para comandos multibyte.
   * - Los datos se envían en formato MSB-first.
   * - Consultar el datasheet para detalles sobre la secuencia de reloj y el formato de los datos.
   */
  void WREG(byte address, byte value);
  /**
   * @brief Lee uno o varios registros del ADS119X mediante SPI.
   *
   * Envía el comando RREG, que permite leer el contenido de uno o más registros internos del dispositivo.
   * El comando consta de dos bytes: el primero indica la dirección inicial del registro, y el segundo el número de registros a leer menos uno.
   *
   * @param address Dirección del registro a leer (ver mapa de registros en el datasheet).
   * @return Valor leído del registro (si se usa para un solo registro).
   *
   * Notas:
   * - Si el dispositivo está en modo de lectura continua de datos (RDATAC), es necesario emitir el comando SDATAC antes de usar RREG.
   * - El pin CS debe mantenerse bajo durante toda la operación.
   * - El comando puede usarse en cualquier momento, pero hay restricciones en la velocidad de SCLK para comandos multibyte.
   * - Consultar el datasheet para detalles sobre la secuencia de reloj y el formato de los datos.
   */
  byte RREG(byte address);
  /**
   * @brief Lee varios registros consecutivos del ADS119X mediante SPI.
   *
   * Permite consultar la configuración de un bloque de registros internos, comenzando en una dirección específica.
   *
   * @param address Dirección inicial del primer registro a leer.
   * @param numRegistersMinusOne Número de registros a leer menos uno (por ejemplo, para leer 3 registros, pasar 2).
   *
   * Notas:
   * - Es recomendable detener la conversión continua (SDATAC) antes de leer registros.
   * - Los valores leídos se almacenan en el buffer interno de la clase.
   * - Consultar el datasheet para interpretar correctamente los valores devueltos.
   */
  void RREGS(byte  address, byte  numRegistersMinusOne); 

  /**
   * @brief Modifica bits específicos de un registro sin afectar los demás.
   *
   * Realiza una operación de lectura-modificación-escritura sobre un registro del ADS119X:
   * lee el valor actual, limpia los bits especificados por la máscara, inserta los nuevos valores
   * y escribe el resultado de vuelta. Esta función preserva automáticamente todos los bits fuera de la máscara.
   *
   * @param address Dirección del registro a modificar (ver mapa de registros en el datasheet).
   * @param mask Máscara de bits a modificar (1 en los bits que se desean cambiar, 0 en los que se preservan).
   * @param value Nuevos valores para los bits especificados por la máscara (solo los bits en la máscara son considerados).
   *
   * Ejemplo de uso:
   * @code
   * // Cambiar la tasa de muestreo sin afectar otros bits de CONFIG1
   * modifyRegister(ADS119X_ADD_CONFIG1, ADS119X_DRATE_MASK, ADS119X_DRATE_500SPS);
   * @endcode
   *
   * Notas:
   * - Usa internamente getRegister() para leer el valor actual del espejo local.
   * - Usa WREG() para escribir el resultado, que actualiza automáticamente el espejo.
   * - Los bits fuera de la máscara se preservan garantizado.
   * - Patrón equivalente: (currentValue & ~mask) | (value & mask).
   * - Útil como alternativa a escribir manualmente el patrón de lectura-modificación-escritura.
   */
  void modifyRegister(byte address, byte mask, byte value);

  /**
   * @brief Configura la tasa de muestreo del ADS119X.
   *
   * Permite seleccionar la frecuencia a la que el dispositivo realiza la conversión de datos, ajustando el ancho de banda y el consumo de energía.
   *
   * @param dataRate Valor de la tasa de muestreo a configurar (usar las constantes definidas, por ejemplo, ADS119X_DRATE_500SPS).
   *
   * Notas:
   * - La tasa de muestreo afecta la resolución temporal y el consumo del sistema.
   * - Consultar el datasheet para conocer los valores válidos y sus efectos.
   * - Es recomendable detener la conversión continua (SDATAC) antes de cambiar la tasa de muestreo.
   */
  void setDataRate(byte dataRate); 
  /**
   * @brief Lee los datos de todos los canales y el estado del ADS119X.
   *
   * Realiza la lectura de los datos de conversión de todos los canales activos y actualiza el buffer interno con los valores obtenidos.
   *
   * Notas:
   * - Debe llamarse cuando la señal DRDY indique que hay nuevos datos disponibles.
   * - Los datos leídos pueden ser accedidos mediante getChannelData().
   * - El estado del dispositivo también se actualiza internamente.
   */
  void readChannelData(); 
  
  /**
   * @brief Indica si hay un nuevo dato disponible (DRDY bajo).
   *
   * Comprueba el estado del pin DRDY del ADS119X, que baja a nivel bajo cuando hay datos de conversión listos para ser leídos.
   * DRDY es una señal de salida del ADS119X que permite sincronizar la lectura de datos sin depender del pin CS.
   *
   * @return true si hay dato disponible (DRDY en bajo), false si no.
   *
   * Notas:
   * - Es fundamental consultar DRDY antes de leer datos para evitar lecturas inválidas.
   * - El comportamiento de DRDY está documentado en el datasheet y es clave para la operación eficiente del dispositivo.
   */
  boolean isDRDY();
  
  /**
   * @brief Configura los parámetros de un canal específico del ADS119X.
   *
   * Permite ajustar el modo de alimentación (power-down), la ganancia del PGA y la configuración del multiplexor de entrada para un canal concreto, escribiendo en el registro CHnSET correspondiente.
   *
   * @param address Dirección del registro CHnSET del canal a configurar (05h a 0Ch).
   * @param pwdownSetting Configuración de power-down (0 = normal, 1 = power-down; recomendado poner MUX en corto si se apaga el canal).
   * @param gainSetting Configuración de ganancia PGA (000=6, 001=1, 010=2, 011=3, 100=4, 101=8, 110=12).
   * @param muxSetting Configuración del multiplexor de entrada (000=entrada normal, 001=entrada en corto, 010=RLD_MEAS, 011=MVDD, 100=temperatura, 101=señal de test, 110=RLD_DRP, 111=RLD_DRN).
   *
   * Notas:
   * - Al poner un canal en power-down, se recomienda configurar el MUX en modo “input short” (001) para minimizar el ruido.
   * - Consultar el datasheet para detalles sobre combinaciones válidas y efectos de cada ajuste.
   * - La configuración del multiplexor permite seleccionar diferentes fuentes de señal para cada canal.
   */
  void setChannelSettings(byte address, byte pwdownSetting, byte gainSetting, byte muxSetting )  ;

  /**
   * @brief Configura los parámetros de todos los canales activos del ADS119X.
   *
   * Aplica la misma configuración de power-down, ganancia y multiplexor a todos los canales
   * detectados en la inicialización, llamando a setChannelSettings() para cada uno.
   *
   * @param pwdownSetting Configuración de power-down (0 = normal, 1 = power-down; recomendado poner MUX en corto si se apaga el canal).
   * @param gainSetting Configuración de ganancia PGA (000=6, 001=1, 010=2, 011=3, 100=4, 101=8, 110=12).
   * @param muxSetting Configuración del multiplexor de entrada (000=entrada normal, 001=entrada en corto, 010=RLD_MEAS, 011=MVDD, 100=temperatura, 101=señal de test, 110=RLD_DRP, 111=RLD_DRN).
   *
   * Notas:
   * - Solo afecta a los canales activos según _num_channels, determinado al leer el ID del dispositivo.
   * - Ver setChannelSettings() para detalles sobre los valores válidos de cada parámetro.
   */
  void setAllChannelSettings(byte pwdownSetting, byte gainSetting, byte muxSetting );

  /**
   * @brief Configura el multiplexor de entrada de todos los canales activos del ADS119X.
   *
   * Aplica la misma configuración de multiplexor a todos los canales activos, conservando
   * los valores actuales de power-down y ganancia de cada canal.
   *
   * @param muxSetting Configuración del multiplexor de entrada (000=entrada normal, 001=entrada en corto, 010=RLD_MEAS, 011=MVDD, 100=temperatura, 101=señal de test, 110=RLD_DRP, 111=RLD_DRN).
   *
   * Notas:
   * - Solo afecta a los canales activos según _num_channels, determinado al leer el ID del dispositivo.
   * - Los ajustes de power-down y ganancia de cada canal no se modifican.
   * - Ver setChannelSettings() para detalles sobre los valores válidos de muxSetting.
   */
  void setAllChannelMux(byte muxSetting );

  /**
   * @brief Configura la ganancia del PGA de todos los canales activos del ADS119X.
   *
   * Aplica la misma configuración de ganancia a todos los canales activos, conservando
   * los valores actuales de power-down y multiplexor de cada canal.
   *
   * @param gainSetting Configuración de ganancia PGA (000=6, 001=1, 010=2, 011=3, 100=4, 101=8, 110=12).
   *
   * Notas:
   * - Solo afecta a los canales activos según _num_channels, determinado al leer el ID del dispositivo.
   * - Los ajustes de power-down y multiplexor de cada canal no se modifican.
   * - Ver setChannelSettings() para detalles sobre los valores válidos de gainSetting.
   */
  void setAllChannelGain(byte gainSetting );  

  /**
   * @brief Devuelve el valor actual de un registro del ADS119X almacenado en el espejo local.
   *
   * Consulta el array interno _regData, que mantiene una copia sincronizada de los registros
   * del dispositivo, sin realizar ninguna comunicación SPI.
   *
   * @param address Dirección del registro a consultar (ver mapa de registros en el datasheet).
   * @return Valor actual del registro en el espejo local.
   *
   * Notas:
   * - Uso principalmente interno para preservar bits no modificados al escribir registros.
   * - El valor devuelto refleja el último estado escrito o leído, no necesariamente el estado
   *   actual del dispositivo si este ha sido modificado externamente.
   */
  byte keepSetting(byte address);
  
  /**
   * @brief Ejecuta la prueba de ruido interno del ADS119X.
   *
   * Configura todos los canales en modo "input short" (CHnSET[2:0] = 001), que conecta
   * la tensión de modo común (AVDD-AVSS)/2 a ambas entradas del canal, eliminando
   * la señal diferencial. Permite medir el ruido inherente del dispositivo en el sistema.
   * Activa la referencia interna, inicia la conversión y captura una muestra.
   *
   * Notas:
   * - Se llama automáticamente desde begin() como parte de la secuencia de inicialización.
   * - Los datos capturados quedan disponibles en el buffer interno, accesibles mediante getChannelData().
   * - No restaura la configuración previa de los canales al finalizar.
   * - Ver sección "Device Noise Measurements" del datasheet para interpretación de resultados.
   */
  void testNoise();

  /**
   * @brief Ejecuta la prueba de señal interna del ADS119X.
   *
   * Configura todos los canales en modo test (CHnSET[2:0] = 101) y activa la generación
   * interna de señal de calibración (INT_TEST = 1), una onda cuadrada de amplitud
   * -1 x (VREFP - VREFN)/2.4mV a frecuencia f_CLK/2^21 (por defecto).
   * Inicia la conversión y captura una muestra.
   *
   * Notas:
   * - Se llama automáticamente desde begin() como parte de la secuencia de inicialización.
   * - Los datos capturados quedan disponibles en el buffer interno, accesibles mediante getChannelData().
   * - No restaura la configuración previa de los canales al finalizar.
   * - No está diseñada para cumplimiento con IEC60601-2-51; es solo para verificación funcional.
   * - Ver sección "Test Signals" y registro CONFIG2 del datasheet para más detalles.
   */
  void testSignal();

  /**
   * @brief Ejecuta la prueba de señal interna DC del ADS119X.
   *
   * Igual que testSignal() pero configura TEST_FREQ[1:0] = 11, generando una señal
   * de calibración continua (DC) en lugar de onda cuadrada.
   *
   * Notas:
   * - No se llama desde begin(); debe invocarse manualmente si se requiere.
   * - Los datos capturados quedan disponibles en el buffer interno, accesibles mediante getChannelData().
   * - No restaura la configuración previa de los canales al finalizar.
   * - Ver registro CONFIG2 del datasheet para más detalles sobre TEST_FREQ.
   */
  void testSignalDC();

  /**
   * @brief Devuelve el registro de estado del ADS119X de la última lectura.
   *
   * Devuelve el valor de los 24 bits de estado capturados en la última llamada a readChannelData(),
   * con el siguiente formato: bits[23:20] = 1100 (fijos), bits[19:12] = LOFF_STATP, bits[11:4] = LOFF_STATN, bits[3:0] = GPIO[7:4].
   *
   * @return Valor de 32 bits con los 24 bits de estado.
   *
   * Notas:
   * - El valor solo se actualiza al llamar a readChannelData().
   * - En LOFF_STATP y LOFF_STATN: 0 = electrodo conectado (lead-on), 1 = electrodo desconectado (lead-off).
   * - Los bits de LOFF_STATP y LOFF_STATN solo son válidos si los bits correspondientes
   *   de LOFF_SENSP (0Fh) y LOFF_SENSN (10h) están habilitados.
   * - Ver registros LOFF_STATP (12h) y LOFF_STATN (13h) del datasheet para interpretación de los bits.
   */
  int32_t getStatus();

  /**
   * @brief Devuelve el dato de un canal del ADS119X de la última lectura.
   *
   * Devuelve el valor de conversión del canal indicado capturado en la última llamada
   * a readChannelData(), representado en complemento a dos de 16 bits.
   *
   * @param channel Índice del canal a consultar (0 = CH1, 1 = CH2, ..., n-1 = CHn).
   * @return Valor de conversión del canal en formato int16_t (complemento a dos).
   *
   * Notas:
   * - El valor solo se actualiza al llamar a readChannelData().
   * - No se comprueba si el índice está dentro del rango de canales activos.
   * - Ver ADS119X_TOTAL_CH en el header para el número máximo de canales.
   */
  int16_t getChannelData(byte channel);  

  /**
   * @brief Devuelve el número total de registros del ADS119X.
   *
   * @return Número de registros del dispositivo (ADS119X_REG_SIZE = 26).
   */
  byte getRegisterSize(); 

  /**
   * @brief Devuelve el valor de un registro del ADS119X almacenado en el espejo local.
   *
   * @param address Dirección del registro a consultar (ver mapa de registros en el datasheet).
   * @return Valor actual del registro en el espejo local.
   *
   * Notas:
   * - Equivalente a keepSetting() pero de acceso público.
   * - El valor refleja el último estado escrito o leído, no necesariamente el estado
   *   actual del dispositivo si este ha sido modificado externamente.
   */
  byte getRegister(byte address); 

  /**
   * @brief Devuelve el número de canales activos del dispositivo.
   *
   * @return Número de canales detectados al leer el registro ID durante begin() (4, 6 u 8).
   */
  byte getNumberOfChannels();
  
  /**
   * @brief Restaura todos los registros del ADS119X a los valores por defecto.
   *
   * Escribe en bloque todos los registros del dispositivo con los valores capturados
   * tras el reset hardware en begin(), y actualiza el espejo local.
   *
   * Notas:
   * - Los valores por defecto corresponden al estado del dispositivo tras el reset,
   *   no necesariamente a los valores de reset del datasheet.
   * - Detiene la conversión continua (SDATAC) antes de escribir los registros.
   * - No reinicia la secuencia de inicialización; para ello usar begin().
   */
  void  setDefaultSettings();   

  /**
   * @brief Sincroniza el espejo local con el estado actual de los registros del ADS119X.
   *
   * Lee en bloque todos los registros del dispositivo mediante SPI y actualiza _regData.
   *
   * Notas:
   * - Debe llamarse con el dispositivo en modo SDATAC.
   * - Usar antes de consultar registros si se sospecha que el estado del dispositivo
   *   ha podido cambiar externamente.
   */
  void  syncRegData();   
   
  
 private:

  /**
   * @brief Envía y recibe un byte mediante SPI.
   *
   * Wrapper de SPI.transfer() para la comunicación con el ADS119X.
   *
   * @param _data Byte a enviar.
   * @return Byte recibido simultáneamente (full-duplex).
   */
  byte xfer(byte _data); 

  /**
   * @brief Activa el pin CS (Chip Select) del ADS119X poniéndolo a nivel bajo.
   *
   * Inicia la comunicación SPI seleccionando el dispositivo.
   */
  void csLow();

  /**
   * @brief Desactiva el pin CS (Chip Select) del ADS119X poniéndolo a nivel alto.
   *
   * Finaliza la comunicación SPI deseleccionando el dispositivo.
   */
  void csHigh();

  /**
   * @brief Determina el número de canales activos a partir del registro ID del ADS119X.
   *
   * Lee los bits DEV_ID[1:0] del registro ID y asigna _num_channels según el modelo
   * detectado (ADS1194 = 4, ADS1196 = 6, ADS1198 = 8). Por defecto asigna 4 canales.
   *
   * Notas:
   * - Se llama automáticamente desde begin() tras validar el ID del dispositivo.
   * - Ver registro ID (00h) del datasheet para el mapa de bits de identificación.
   */
  void getNumberOfChannelsFromReg ();
  
// Pines de control y comunicación SPI
  byte _drdy_pin;     // Pin DRDY: entrada, indica dato listo (activo en bajo).
  byte _reset_pin;    // Pin RESET: salida, reinicia el dispositivo (activo en bajo).
  byte _cs_pin;       // Pin CS: salida, selecciona el dispositivo SPI (activo en bajo).
  byte _clk_pin;      // Pin SCLK: salida, reloj SPI.
  byte _miso_pin;     // Pin MISO: entrada, datos SPI del ADS119X al micro.
  byte _mosi_pin;     // Pin MOSI: salida, datos SPI del micro al ADS119X.
    
  //-------- Espejo local de registros y configuración
  byte _regData[ADS119X_REG_SIZE];        // Copia local de los registros del dispositivo, actualizada en cada WREG/RREG.
  byte _regDataDefault[ADS119X_REG_SIZE]; // Valores de los registros tras el reset, guardados en begin().
  byte _num_channels;                     // Número de canales activos, determinado al leer el registro ID.
  int16_t _channelData[ADS119X_TOTAL_CH]; // Buffer de datos de los canales, actualizado en readChannelData().
  uint32_t _boardStat;                    // Registro de estado de 24 bits, actualizado en readChannelData().
  
};

#endif