clear; clc; close all;

sps = 500; %frecuencia de muestreo del ADS
tReposo = [0.5 2.5]; %[inicio fin] en s del tramo de reposo (cambiar según la muestra)

%===================Elegir fichero y cargar tabla CSV=====================

carpetaInicial = "C:\Users\Carlo\Documents\REPOSITORIOS\Pr-tesis.V\firmware\EMG\data\raw";
[archivo, carpeta] = elegirMuestra(carpetaInicial);
data = readtable(fullfile(carpeta, archivo), 'VariableNamingRule', 'modify');

%========================================================================

ch0 = data{:,2}; %Columna 2 porque la anterior es de tiempo
ch1 = data{:,3};
nMuestras = length(ch0);
t = (0:nMuestras-1)' / sps; %Vector muestra => vector tiempo
fprintf('N = %d muestras, duración = %.2f s\n', nMuestras, t(end));

vRefADS = 2.4; %Depende de CONFIG3 PD_REFBUF=1 (activado)
%y depende de si Vref_4V = 0 en el registro.
gainADS = 4; %Depende de la ganancia configurada actualmente 4
resolucionADS = 2^16; %Nuestro ADS tiene 16 bits
fondoDeEscala = vRefADS/gainADS; %Refe sobre Gain es lo máximo a obtener
%Como fondoDeEscala varía desde negativo a positivo para tomar 
%todos los valores (valor pico pico) serán valor pico *2
pasoMicroVolt = 2*fondoDeEscala/resolucionADS * 1e6; %obtenemos el valor de paso

%Centramos la señal respecto al 0

v0 = (ch0 - mean(ch0)) * pasoMicroVolt; %Canal 0 en uV centrado
v1 = (ch1 - mean(ch1)) * pasoMicroVolt; %canal 1 en uV centrado

TT = timetable(v0,v1, 'SampleRate', sps);
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

percentAt50hz_ch0 = bandpower(v0,sps,[49 51]) / bandpower(v0,sps,[1 249])*100;
percentAt50hz_ch1 = bandpower(v1,sps,[49 51]) / bandpower(v1,sps,[1 249])*100;
fprintf('50 Hz: %.0f %% (canal 0), %.0f %% (canal 1)\n', percentAt50hz_ch0,percentAt50hz_ch1);

%================Filtro notch 50Hz =======================================

f0 = 50; %Frecuencia a eliminar
Q = 35; %Factor de calidad: lo más recomendado para este caso 35
%La frecuencia de Nyquist es un teorema básico de muestreo
%con una f de muestreo solo se puede ver frecuencias hasta la mitad
fNyquist = sps/2; %Frecuencia de Nyquist
w0 = f0/fNyquist; %f0 normalizada respecto a Nyquist
anchoNotchNormaliz = w0/Q; %ancho notch normalizado

%Obtengo los coeficientes del filtro con la funcion iirnotch()
[bNotch, aNotch] = iirnotch(w0, anchoNotchNormaliz);

%Filtfilt aplica el filtro hacia adelante y hacia atras
%elimina los 50Hz sin desfasar la señal
v0notch = filtfilt(bNotch,aNotch,v0); %Canal 0 con filtro notch
v1notch = filtfilt(bNotch, aNotch, v1); % Canal 1 con filtro notch

%Gráfica antes y después del filtro notch
figure
subplot(2,1,1);
pspectrum(v0,sps);
hold on
pspectrum(v0notch,sps);
legend('Original','Notch');
title('Canal 0');
subplot(2,1,2);
pspectrum(v1,sps);
hold on;
pspectrum(v1notch,sps);
legend('Original','Notch');
title('Canal 1');

%Potencia en 50 Hz con el filtro notch

percentAt50hz_ch0notch = bandpower(v0notch,sps,[49 51]) / bandpower(v0notch,sps,[1 249])*100;
percentAt50hz_ch1notch = bandpower(v1notch,sps,[49 51]) / bandpower(v1notch,sps,[1 249])*100;
fprintf('50 Hz: %.1f %% (canal 0), %.1f %% (canal 1)\n', percentAt50hz_ch0notch,percentAt50hz_ch1notch);

%===============Pasa banda 20-240Hz========================================

fBanda = [20 240]; %Banda de señal últil (EMG)

[v0fBanda, dBanda] = bandpass(v0notch,fBanda,sps); %Notch + Pasabanda (y guardo el filtro)
v1fBanda = bandpass(v1notch,fBanda,sps);

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
pspectrum(v0notch,sps)
hold on
pspectrum(v0fBanda,sps)
legend('Solo notch', 'Notch + paso banda')
title('Canal 0')
subplot(2,1,2)
pspectrum(v1notch,sps)
hold on
pspectrum(v1fBanda,sps)
legend('Solo notch','Notch + paso banda')
title('Canal 1')

%=======================Espectrograma===================================
tVentana = 0.25; %Duracion de cada ventana [s]

figure
subplot(2,1,1)
pspectrum(v0fBanda,sps,'spectrogram','TimeResolution',tVentana,...
    'OverlapPercent',75)
title('Canal 0 - espectrograma')
subplot(2,1,2)
pspectrum(v1fBanda,sps,'spectrogram','TimeResolution',tVentana,...
    'OverlapPercent',75)
title('Canal 1 - espectrograma')

%====================Envolvente RMS====================================
tRMS = 0.2; %Ventana de tiempo RMS
W = round(tRMS*sps); %Calculamos W muestras que caben en la ventana

rms0 = envelope(v0fBanda, W, 'rms'); %Envolvente canal 0 [uV]
rms1 = envelope(v1fBanda,W,'rms'); 

%Umbral de activación: nivel de reposo + 3 desviaciones típicas.
reposo  = t >= tReposo(1) & t < tReposo(2); %Tramo que tomamos como estado de reposo
umbral0 = mean(rms0(reposo)) + 3*std(rms0(reposo));
umbral1 = mean(rms1(reposo)) + 3*std(rms1(reposo));

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

resultados = table(string(archivo), nMuestras, nMuestras/sps, ...
    percentAt50hz_ch0, percentAt50hz_ch1, ...
    percentAt50hz_ch0notch, percentAt50hz_ch1notch, ...
    mean(rms0(reposo)), mean(rms1(reposo)), umbral0, umbral1, tRMS, ...
    'VariableNames', {'muestra','nMuestras','duracion_s', ...
    'p50_ch0','p50_ch1','p50notch_ch0','p50notch_ch1', ...
    'rmsReposo_ch0_uV','rmsReposo_ch1_uV','umbral_ch0_uV','umbral_ch1_uV','tRMS_s'});
guardarResultados(destino, carpetaDestino, resultados);

save(fullfile(destino, "senales.mat"), "t", "v0fBanda", "v1fBanda", "rms0", "rms1");
guardarFiltros(destino, sps, f0, Q, bNotch, aNotch, fBanda, dBanda, tRMS, W);