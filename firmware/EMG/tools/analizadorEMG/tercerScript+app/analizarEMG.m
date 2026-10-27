function res = analizarEMG(ch0, ch1, p)
%ANALIZAREMG Procesa dos canales EMG del ADS sin hacer ninguna gráfica.
%   res = analizarEMG(ch0, ch1, p) hace todo el cálculo del análisis:
%     1. Convierte las cuentas del ADC a uV y centra la señal en 0.
%     2. Calcula el % de potencia en la frecuencia de red (f0 ± 1 Hz).
%     3. Aplica el notch en f0 con filtfilt (si p.notchOn).
%     4. Aplica el paso banda p.fBanda (si p.bandaOn).
%     5. Calcula la envolvente RMS con ventana p.tRMS.
%     6. Calcula el umbral = media + p.kUmbral·std de la RMS en p.tReposo.
%   Si un filtro está desactivado, la señal pasa sin cambios a la
%   siguiente etapa.
%
%   Entradas:
%     ch0, ch1 - cuentas del ADC de cada canal (vectores columna)
%     p        - struct de parámetros con los campos:
%                sps [Hz], vRef [V], ganancia, nBitsADC,
%                notchOn, f0 [Hz], Q,
%                bandaOn, fBanda [Hz] ([inferior superior]),
%                tRMS [s], tReposo [s] ([inicio fin]), kUmbral
%                (tVentana no se usa aquí, solo en el espectrograma)
%
%   Salida:
%     res - struct con:
%       p                          - copia de los parámetros usados
%       avisos                     - avisos de validarParametros ({} si no hay)
%       nMuestras, t               - nº de muestras y vector tiempo [s]
%       v0, v1                     - señal centrada [uV]
%       p50_ch0, p50_ch1           - % de potencia en f0, señal bruta
%       bNotch, aNotch             - coeficientes del notch (1 y 1 si está apagado)
%       v0notch, v1notch           - señal tras el notch [uV]
%       p50notch_ch0, p50notch_ch1 - % de potencia en f0 tras el notch
%       dBanda                     - filtro paso banda ([] si está apagado)
%       v0fBanda, v1fBanda         - señal tras notch + paso banda [uV]
%       W                          - ventana RMS [muestras]
%       rms0, rms1                 - envolvente RMS [uV]
%       reposo                     - máscara lógica del tramo de reposo
%       rmsReposo_ch0, _ch1        - RMS media en reposo [uV]
%       umbral0, umbral1           - umbral de activación [uV]
%
%   Ejemplo:
%     res = analizarEMG(data{:,2}, data{:,3}, p);
%     plot(res.t, res.rms0); yline(res.umbral0);
%
%   Nota: usa filtfilt (no causal), válido para analizar en PC pero no
%   para tiempo real en el ESP32 (ver tareas G1-G4).

res.p = p; %Guardamos los parámetros usados junto a los resultados

%Comprobamos los parámetros antes de calcular nada: si alguno no tiene
%sentido salta un error con un mensaje claro; si solo es dudoso, un aviso
res.avisos = validarParametros(p, length(ch0));

nMuestras = length(ch0);
res.nMuestras = nMuestras;
res.t = (0:nMuestras-1)' / p.sps; %Vector muestra => vector tiempo

%======================Conversión a uV=================================
fondoDeEscala = p.vRef/p.ganancia; %Refe sobre Gain es lo máximo a obtener
%Como fondoDeEscala varía desde negativo a positivo para tomar 
%todos los valores (valor pico pico) serán valor pico *2
pasoMicroVolt = 2*fondoDeEscala/2^p.nBitsADC * 1e6; %obtenemos el valor de paso

%Centramos la señal respecto al 0
res.v0 = (ch0 - mean(ch0)) * pasoMicroVolt; %Canal 0 en uV centrado
res.v1 = (ch1 - mean(ch1)) * pasoMicroVolt; %canal 1 en uV centrado

%Cuanto afecta la banda de 50hz en porcentaje
bandaRed  = [p.f0-1 p.f0+1]; %Banda alrededor de la frecuencia de red
bandaTotal = [1 p.sps/2-1];  %Toda la banda visible (hasta Nyquist)
res.p50_ch0 = bandpower(res.v0,p.sps,bandaRed) / bandpower(res.v0,p.sps,bandaTotal)*100;
res.p50_ch1 = bandpower(res.v1,p.sps,bandaRed) / bandpower(res.v1,p.sps,bandaTotal)*100;

%================Filtro notch 50Hz =======================================
if p.notchOn
    %La frecuencia de Nyquist es un teorema básico de muestreo
    %con una f de muestreo solo se puede ver frecuencias hasta la mitad
    fNyquist = p.sps/2; %Frecuencia de Nyquist
    w0 = p.f0/fNyquist; %f0 normalizada respecto a Nyquist
    %Obtengo los coeficientes del filtro con designNotchPeakIIR()
    %(sustituye a iirnotch, que MATLAB va a retirar). Orden 2 por defecto,
    %así bNotch y aNotch siguen siendo vectores de 3 coeficientes
    [res.bNotch, res.aNotch] = designNotchPeakIIR(Response="notch", ...
        CenterFrequency=w0, QualityFactor=p.Q);

    %Filtfilt aplica el filtro hacia adelante y hacia atras
    %elimina los 50Hz sin desfasar la señal
    res.v0notch = filtfilt(res.bNotch, res.aNotch, res.v0); %Canal 0 con filtro notch
    res.v1notch = filtfilt(res.bNotch, res.aNotch, res.v1); %Canal 1 con filtro notch
else
    res.bNotch = 1; res.aNotch = 1; %Filtro "neutro": no cambia la señal
    res.v0notch = res.v0;
    res.v1notch = res.v1;
end

%Potencia en 50 Hz con el filtro notch
res.p50notch_ch0 = bandpower(res.v0notch,p.sps,bandaRed) / bandpower(res.v0notch,p.sps,bandaTotal)*100;
res.p50notch_ch1 = bandpower(res.v1notch,p.sps,bandaRed) / bandpower(res.v1notch,p.sps,bandaTotal)*100;

%===============Pasa banda=================================================
if p.bandaOn
    %Forzamos FIR: por defecto bandpass pasa a IIR cuando el FIR saldría
    %demasiado largo (cortes muy cerca de 0 Hz o de sps/2), y ese IIR puede
    %ser inestable y dar picos falsos en los cortes. El FIR siempre es estable
    try
        [res.v0fBanda, res.dBanda] = bandpass(res.v0notch,p.fBanda,p.sps,'ImpulseResponse','fir'); %Notch + Pasabanda (y guardo el filtro)
        res.v1fBanda = bandpass(res.v1notch,p.fBanda,p.sps,'ImpulseResponse','fir');
    catch errBanda
        error('analizarEMG:banda', ['No se puede aplicar el paso banda %g-%g Hz a esta señal: ' ...
            'con un corte tan cerca de 0 Hz o de %g Hz (sps/2) el filtro necesitaría más muestras ' ...
            'de las que tiene la señal. Aleja los cortes de los extremos.\n(MATLAB: %s)'], ...
            p.fBanda(1), p.fBanda(2), p.sps/2, errBanda.message);
    end
else
    res.dBanda = [];
    res.v0fBanda = res.v0notch;
    res.v1fBanda = res.v1notch;
end

%====================Envolvente RMS====================================
res.W = round(p.tRMS*p.sps); %Calculamos W muestras que caben en la ventana

res.rms0 = envelope(res.v0fBanda, res.W, 'rms'); %Envolvente canal 0 [uV]
res.rms1 = envelope(res.v1fBanda, res.W, 'rms');

%Umbral de activación: nivel de reposo + k desviaciones típicas.
res.reposo = res.t >= p.tReposo(1) & res.t < p.tReposo(2); %Tramo que tomamos como estado de reposo
res.rmsReposo_ch0 = mean(res.rms0(res.reposo));
res.rmsReposo_ch1 = mean(res.rms1(res.reposo));
res.umbral0 = res.rmsReposo_ch0 + p.kUmbral*std(res.rms0(res.reposo));
res.umbral1 = res.rmsReposo_ch1 + p.kUmbral*std(res.rms1(res.reposo));
end
