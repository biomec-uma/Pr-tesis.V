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
data = readtable(fullfile(carpeta, archivo), 'VariableNamingRule', 'preserve');

%========================================================================

ch0 = data{:,2}; %Columna 2 porque la anterior es de tiempo
ch1 = data{:,3};

%======================Análisis (sin gráficas)=========================
res = analizarEMG(ch0, ch1, p);
fprintf('N = %d muestras, duración = %.2f s\n', res.nMuestras, res.t(end));
fprintf('50 Hz: %.0f %% (canal 0), %.0f %% (canal 1)\n', res.p50_ch0, res.p50_ch1);
fprintf('50 Hz tras notch: %.1f %% (canal 0), %.1f %% (canal 1)\n', res.p50notch_ch0, res.p50notch_ch1);
fprintf('Umbral: %.0f uV (canal 0), %.0f uV (canal 1)\n', res.umbral0, res.umbral1);

%==============================Gráficas==================================
%Señal bruta centrada
figure
ax = [subplot(2,1,1), subplot(2,1,2)];
graficarBruta(res, ax);

%Análisis en el dominio de la frecuencia
figure
ax = [subplot(2,1,1), subplot(2,1,2)];
graficarEspectro(res, ax);

%Gráfica antes y después del filtro notch
figure
ax = [subplot(2,1,1), subplot(2,1,2)];
graficarNotch(res, ax);

%Gráfica antes y después del pasabanda.
figure
ax = [subplot(2,1,1), subplot(2,1,2)];
graficarFiltrada(res, ax);

%Espectro antes y después del paso banda
figure
ax = [subplot(2,1,1), subplot(2,1,2)];
graficarBanda(res, ax);

%Espectrograma
figure
ax = [subplot(2,1,1), subplot(2,1,2)];
graficarEspectrograma(res, ax);

%EMG filtrada y envolvente RMS
figure
ax = [subplot(2,1,1), subplot(2,1,2)];
graficarEnvolvente(res, ax);
%==============================Guardar===================================
carpetaDestino = "C:\Users\Carlo\Documents\REPOSITORIOS\Pr-tesis.V\firmware\EMG\data\processed\OutputAnalisis";
guardarAnalisis(res, archivo, carpetaDestino);