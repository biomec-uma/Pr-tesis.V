function destino = guardarAnalisis(res, archivo, carpetaDestino, figs)
%GUARDARANALISIS Guarda todos los resultados del análisis de una muestra.
%   destino = guardarAnalisis(res, archivo, carpetaDestino) crea la
%   subcarpeta carpetaDestino\<nombre de la muestra> y guarda en ella:
%     figura_N.png             - las figuras de figs o, si no se pasa,
%                                todas las abiertas (guardarFiguras)
%     resultados.csv           - resultados y parámetros de esta muestra
%     resumen_muestras.csv     - historial: una fila por cada guardado
%     senales.mat              - t, v0fBanda, v1fBanda, rms0, rms1
%     filtros.mat              - filtros y parámetros (guardarFiltros)
%     coeficientes_filtros.txt - coeficientes en texto (guardarFiltros)
%
%   Entradas:
%     res            - struct de resultados de analizarEMG
%     archivo        - nombre del CSV analizado (de elegirMuestra)
%     carpetaDestino - carpeta raíz de resultados (string)
%     figs           - (opcional) vector de figuras a guardar, p.ej. las
%                      ocultas de crearFiguras(res,'off'). Es lo que usa la app
%   Salida:
%     destino - ruta de la subcarpeta de la muestra
%
%   Ejemplo:
%     destino = guardarAnalisis(res, archivo, "C:\...\processed\OutputAnalisis");
%     destino = guardarAnalisis(res, archivo, carpetaDestino, figs);  %App
%
%   Nota: sin figs, las figuras deben estar abiertas antes de llamarla,
%   porque guardarFiguras exporta las que encuentre. Sobrescribe los
%   archivos si la muestra ya se había analizado.

p = res.p; %Parámetros con los que se hizo el análisis

%Figuras
if nargin < 4       %Sin lista: todas las abiertas (script)
    destino = guardarFiguras(carpetaDestino, archivo);
else                %Con lista: solo esas (app)
    destino = guardarFiguras(carpetaDestino, archivo, figs);
end

%Tabla de resultados: valores calculados + parámetros con los que se
%obtuvieron, para poder comparar filas del resumen hechas con ajustes distintos
resultados = table(string(archivo), res.nMuestras, res.nMuestras/p.sps, ...
    res.p50_ch0, res.p50_ch1, ...
    res.p50notch_ch0, res.p50notch_ch1, ...
    res.rmsReposo_ch0, res.rmsReposo_ch1, res.umbral0, res.umbral1, ...
    p.sps, p.notchOn, p.f0, p.Q, p.bandaOn, p.fBanda(1), p.fBanda(2), ...
    p.tRMS, p.tReposo(1), p.tReposo(2), p.kUmbral, ...
    'VariableNames', {'muestra','nMuestras','duracion_s', ...
    'p50_ch0','p50_ch1','p50notch_ch0','p50notch_ch1', ...
    'rmsReposo_ch0_uV','rmsReposo_ch1_uV','umbral_ch0_uV','umbral_ch1_uV', ...
    'sps','notchOn','f0_Hz','Q','bandaOn','fBaja_Hz','fAlta_Hz', ...
    'tRMS_s','tReposoIni_s','tReposoFin_s','kUmbral'});
guardarResultados(destino, resultados);

%Señales procesadas (mismos nombres de variable que en V0)
t = res.t; v0fBanda = res.v0fBanda; v1fBanda = res.v1fBanda;
rms0 = res.rms0; rms1 = res.rms1;
save(fullfile(destino, "senales.mat"), "t", "v0fBanda", "v1fBanda", "rms0", "rms1");

%Filtros
guardarFiltros(destino, p.sps, p.f0, p.Q, res.bNotch, res.aNotch, p.fBanda, res.dBanda, p.tRMS, res.W);
end