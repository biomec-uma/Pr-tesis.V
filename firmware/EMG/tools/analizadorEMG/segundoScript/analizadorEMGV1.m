clear; clc; close all;

%=========================Parámetros========================
% Adquisición
p.sps        = 500;      % [Hz o Samples/s] Frec. Muestreo ADC
p.vRef       = 2.4;      % [V] Tension de referencia del ADC
                         % Depende de CONFIG3 PD_REFBUF=1 (activado)
                         % y depende de si Vref_4V = 0 en el registro.
p.ganancia   = 4;        % Depende de la ganancia configurada actualmente 4
p.nBitsADC   = 16;       %Resolución del conversor ADC
% Notch
p.notchOn    = true;     % Activar notch
p.f0         = 50;       % [Hz] Frecuencia de la red. España 50Hz
p.Q          = 35;       %Factor de Calidad: lo más recomendado para este caso 35
% Paso banda
p.bandaOn    = true;
p.fBanda     = [20 240]; % [Hz] Ancho de banda del filtro (señal útil EMG)
% Análisis
p.tVentana   = 0.25;     % espectrograma: duración de cada ventana [s]
p.tRMS       = 0.2;      % envolvente: ventana de tiempo RMS [s]
p.tReposo    = [0.5 2.5];% [inicio fin] en s del tramo de reposo (cambiar según la muestra)
p.kUmbral    = 3;        % umbral = media + k·std .Desviacion típica

%===================Elegir fichero y cargar tabla CSV=====================

carpetaInicial = "C:\Users\Carlo\Documents\REPOSITORIOS\Pr-tesis.V\firmware\EMG\data\raw";
[archivo, carpeta] = elegirMuestra(carpetaInicial);
data = readtable(fullfile(carpeta, archivo), 'VariableNamingRule', 'modify');

%========================================================================

ch0 = data{:,2}; %Columna 2 porque la anterior es de tiempo
ch1 = data{:,3};
nMuestras = length(ch0);
t = (0:nMuestras-1)' / p.sps; %Vector muestra => vector tiempo
fprintf('N = %d muestras, duración = %.2f s\n', nMuestras, t(end));

fondoDeEscala = p.vRef/p.ganancia; %Refe sobre Gain es lo máximo a obtener
%Como fondoDeEscala varía desde negativo a positivo para tomar 
%todos los valores (valor pico pico) serán valor pico *2
pasoMicroVolt = 2*fondoDeEscala/2^p.nBitsADC * 1e6; %obtenemos el valor de paso

%Centramos la señal respecto al 0

v0 = (ch0 - mean(ch0)) * pasoMicroVolt; %Canal 0 en uV centrado
v1 = (ch1 - mean(ch1)) * pasoMicroVolt; %canal 1 en uV centrado

TT = timetable(v0,v1, 'SampleRate', p.sps);
fprintf('N = %d muestras, duración = %.2f s\n', height(TT), ...
    seconds(TT.Time(end)));

%Graficamos
figure
subplot(2,1,1);
plot(t,v0);
grid on;
ylabel('Canal 0 [\muV]');
title('Señal bruta centrada');
subplot(2,1,2);
plot(t, v1);
grid on;
xlabel('Tiempo [s]');
ylabel('Canal 1 [\muV]');
title('Señal bruta centrada');

%Análisis en el dominio de la frecuencia
%y cuanto afecta la banda de 50hz en porcentaje

figure
subplot(2,1,1); 
pspectrum(TT(:,'v0'));
title('Canal 0');
subplot(2,1,2);
pspectrum(TT(:,'v1'));
title('Canal 1');

bandaRed  = [p.f0-1 p.f0+1]; %Banda alrededor de la frecuencia de red
bandaTotal = [1 p.sps/2-1];  %Toda la banda visible (hasta Nyquist)
percentAt50hz_ch0 = bandpower(v0,p.sps,bandaRed) / bandpower(v0,p.sps,bandaTotal)*100;
percentAt50hz_ch1 = bandpower(v1,p.sps,bandaRed) / bandpower(v1,p.sps,bandaTotal)*100;
fprintf('50 Hz: %.0f %% (canal 0), %.0f %% (canal 1)\n', percentAt50hz_ch0,percentAt50hz_ch1);

%================Filtro notch 50Hz =======================================

%La frecuencia de Nyquist es un teorema básico de muestreo
%con una f de muestreo solo se puede ver frecuencias hasta la mitad
fNyquist = p.sps/2; %Frecuencia de Nyquist
w0 = p.f0/fNyquist; %f0 normalizada respecto a Nyquist
anchoNotchNormaliz = w0/p.Q; %ancho notch normalizado

%Obtengo los coeficientes del filtro con la funcion iirnotch()
[bNotch, aNotch] = iirnotch(w0, anchoNotchNormaliz);

%Filtfilt aplica el filtro hacia adelante y hacia atras
%elimina los 50Hz sin desfasar la señal
v0notch = filtfilt(bNotch,aNotch,v0); %Canal 0 con filtro notch
v1notch = filtfilt(bNotch, aNotch, v1); % Canal 1 con filtro notch

%Gráfica antes y después del filtro notch
figure
subplot(2,1,1);
pspectrum(v0,p.sps);
hold on
pspectrum(v0notch,p.sps);
legend('Original','Notch');
title('Canal 0');
subplot(2,1,2);
pspectrum(v1,p.sps);
hold on;
pspectrum(v1notch,p.sps);
legend('Original','Notch');
title('Canal 1');

%Potencia en 50 Hz con el filtro notch

percentAt50hz_ch0notch = bandpower(v0notch,p.sps,bandaRed) / bandpower(v0notch,p.sps,bandaTotal)*100;
percentAt50hz_ch1notch = bandpower(v1notch,p.sps,bandaRed) / bandpower(v1notch,p.sps,bandaTotal)*100;
fprintf('50 Hz: %.1f %% (canal 0), %.1f %% (canal 1)\n', percentAt50hz_ch0notch,percentAt50hz_ch1notch);

%===============Pasa banda 20-240Hz========================================

[v0fBanda, dBanda] = bandpass(v0notch,p.fBanda,p.sps); %Notch + Pasabanda (y guardo el filtro)
v1fBanda = bandpass(v1notch,p.fBanda,p.sps);

%Gráfica antes y después del pasabanda.

figure
subplot(2,1,1);
plot(t, v0);
hold on
plot(t, v0fBanda);
grid on
legend('Bruta','Filtrada')
ylabel('Canal 0 [\muV]');
title('Señal bruta vs filtrada')
subplot(2,1,2)
plot(t,v1);
hold on
plot(t, v1fBanda)
grid on
legend('Bruta','Filtrada')
xlabel('Tiempo [s]')
ylabel('Canal 1 [\muV]')

figure
subplot(2,1,1)
pspectrum(v0notch,p.sps)
hold on
pspectrum(v0fBanda,p.sps)
legend('Solo notch', 'Notch + paso banda')
title('Canal 0')
subplot(2,1,2)
pspectrum(v1notch,p.sps)
hold on
pspectrum(v1fBanda,p.sps)
legend('Solo notch','Notch + paso banda')
title('Canal 1')

%=======================Espectrograma===================================

figure
subplot(2,1,1)
pspectrum(v0fBanda,p.sps,'spectrogram','TimeResolution',p.tVentana,...
    'OverlapPercent',75)
title('Canal 0 - espectrograma')
subplot(2,1,2)
pspectrum(v1fBanda,p.sps,'spectrogram','TimeResolution',p.tVentana,...
    'OverlapPercent',75)
title('Canal 1 - espectrograma')

%====================Envolvente RMS====================================
W = round(p.tRMS*p.sps); %Calculamos W muestras que caben en la ventana

rms0 = envelope(v0fBanda, W, 'rms'); %Envolvente canal 0 [uV]
rms1 = envelope(v1fBanda,W,'rms'); 

%Umbral de activación: nivel de reposo + k desviaciones típicas.
reposo  = t >= p.tReposo(1) & t < p.tReposo(2); %Tramo que tomamos como estado de reposo
umbral0 = mean(rms0(reposo)) + p.kUmbral*std(rms0(reposo));
umbral1 = mean(rms1(reposo)) + p.kUmbral*std(rms1(reposo));

figure
subplot(2,1,1)
plot(t,v0fBanda,'Color',[0.6 0.6 0.6])
hold on
plot(t, rms0, 'LineWidth',2)
yline(umbral0, "--r",'Umbral')
grid on
ylabel('Canal 0 [\muV]')
title('EMG Filtrado y envolvente RMS')
subplot(2,1,2)
plot(t,v1fBanda,'Color',[0.6 0.6 0.6])
hold on
plot(t,rms1,'LineWidth',2)
yline(umbral1,"--r",'Umbral')
grid on
ylabel('Canal 1 [\muV]')
xlabel('Tiempo [s]')

fprintf('Umbral: %.0f uV (canal 0), %.0f uV (canal 1)\n', umbral0, umbral1)


%==============================Guardar===================================
carpetaDestino = "C:\Users\Carlo\Documents\REPOSITORIOS\Pr-tesis.V\firmware\EMG\data\processed\OutputAnalisis";
destino = guardarFiguras(carpetaDestino, archivo);

resultados = table(string(archivo), nMuestras, nMuestras/p.sps, ...
    percentAt50hz_ch0, percentAt50hz_ch1, ...
    percentAt50hz_ch0notch, percentAt50hz_ch1notch, ...
    mean(rms0(reposo)), mean(rms1(reposo)), umbral0, umbral1, p.tRMS, ...
    'VariableNames', {'muestra','nMuestras','duracion_s', ...
    'p50_ch0','p50_ch1','p50notch_ch0','p50notch_ch1', ...
    'rmsReposo_ch0_uV','rmsReposo_ch1_uV','umbral_ch0_uV','umbral_ch1_uV','tRMS_s'});
guardarResultados(destino, carpetaDestino, resultados);

save(fullfile(destino, "senales.mat"), "t", "v0fBanda", "v1fBanda", "rms0", "rms1");
guardarFiltros(destino, p.sps, p.f0, p.Q, bNotch, aNotch, p.fBanda, dBanda, p.tRMS, W);