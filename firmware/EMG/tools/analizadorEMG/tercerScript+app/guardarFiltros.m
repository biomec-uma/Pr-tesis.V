function guardarFiltros(destino, sps, f0, Q, bNotch, aNotch, fBanda, dBanda, tRMS, W)
%GUARDARFILTROS Guarda los filtros y parámetros usados en el análisis.
%   guardarFiltros(destino, sps, f0, Q, bNotch, aNotch, fBanda, dBanda, tRMS, W)
%   escribe en destino:
%     filtros.mat              - todas las variables, para recargarlas
%                                con load y reutilizar los filtros
%     coeficientes_filtros.txt - coeficientes en texto legible
%
%   Entradas:
%     sps            - frecuencia de muestreo [Hz]
%     f0, Q          - frecuencia [Hz] y factor de calidad del notch
%     bNotch, aNotch - coeficientes del notch (de designNotchPeakIIR); 1 y 1 si
%                      el notch está desactivado
%     fBanda         - banda del paso banda [Hz], p.ej. [20 240]
%     dBanda         - filtro paso banda (2ª salida de bandpass); [] si
%                      el paso banda está desactivado
%     tRMS, W        - ventana de la envolvente RMS [s] y [muestras]
%
%   Uso posterior:
%     load filtros.mat
%     y = filtfilt(bNotch, aNotch, x);   % aplicar el notch a otra señal
%
%   Nota: el paso banda es un FIR largo (~1157 coef.), válido para
%   analizar en PC pero no para tiempo real en el ESP32.
save(fullfile(destino, "filtros.mat"), "sps", "f0", "Q", "bNotch", "aNotch", "fBanda", "dBanda", "tRMS", "W");
fid = fopen(fullfile(destino, "coeficientes_filtros.txt"), "w");
fprintf(fid, "fs = %d Hz\n\n", sps);
%Si bNotch y aNotch valen 1 es el filtro "neutro": el notch estaba apagado
if isequal(bNotch, 1) && isequal(aNotch, 1)
    fprintf(fid, "Notch desactivado\n\n");
else
    fprintf(fid, "Notch %g Hz, Q = %g\n", f0, Q);
    fprintf(fid, "b = [%s]\n", strjoin(string(num2str(bNotch(:), '%.10g')), ", "));
    fprintf(fid, "a = [%s]\n\n", strjoin(string(num2str(aNotch(:), '%.10g')), ", "));
end
if isempty(dBanda) %Paso banda desactivado (p.bandaOn = false)
    fprintf(fid, "Paso banda desactivado\n");
else
    fprintf(fid, "Paso banda %g-%g Hz (%d coeficientes)\n", fBanda(1), fBanda(2), numel(dBanda.Coefficients));
    fprintf(fid, "%s\n", strjoin(string(num2str(dBanda.Coefficients(:), '%.10g')), ", "));
end
fclose(fid);
end