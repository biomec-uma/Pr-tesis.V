clear; clc; close all;

sps = 500; %frecuencia de muestreo del ADS
data = readtable("20.10.2026.antebrazoluegobicep.csv");

ch0 = data{:,2}; %Columna 2 porque la anterior es de tiempo
ch1 = data{:,3};
nMuestras = length(data.data0);
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