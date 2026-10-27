function graficarEspectrograma(res, ax)
%GRAFICARESPECTROGRAMA Dibuja el espectrograma de la señal filtrada.
%   graficarEspectrograma(res, ax) pinta, para cada canal, cómo cambia el
%   espectro de potencia a lo largo del tiempo (eje x tiempo, eje y
%   frecuencia, color potencia en dB). Sirve para ver en qué instantes y
%   en qué frecuencias aparecen las ráfagas EMG o el ruido de motores.
%
%   Entradas:
%     res - struct de resultados de analizarEMG (usa v0fBanda, v1fBanda,
%           p.sps y p.tVentana)
%     ax  - vector de 2 ejes [eje canal 0, eje canal 1]. Pueden ser
%           subplots de una figure (script) o uiaxes (app)
%
%   Ejemplo (script):
%     figure
%     ax = [subplot(2,1,1), subplot(2,1,2)];
%     graficarEspectrograma(res, ax);
%
%   Nota: ventanas de p.tVentana segundos con 75 % de solape, igual que
%   el script original. La función local dibujarEspectrograma hace el
%   mismo truco que dibujarEspectro: pide los datos a pspectrum y los
%   pinta en el eje indicado.

dibujarEspectrograma(ax(1), res.v0fBanda, res.p.sps, res.p.tVentana);
title(ax(1), 'Canal 0 - espectrograma');

dibujarEspectrograma(ax(2), res.v1fBanda, res.p.sps, res.p.tVentana);
title(ax(2), 'Canal 1 - espectrograma');
end


function dibujarEspectrograma(ax, x, sps, tVentana)
%DIBUJARESPECTROGRAMA Espectrograma de x en el eje ax (función local).
%   Entradas:
%     ax       - eje donde dibujar
%     x        - señal (vector) [uV]
%     sps      - frecuencia de muestreo [Hz]
%     tVentana - duración de cada ventana [s]

%s: potencia (lineal) por frecuencia y ventana, f: frecuencias [Hz],
%tt: instante central de cada ventana [s]
[s, f, tt] = pspectrum(x, sps, 'spectrogram', ...
    'TimeResolution', tVentana, 'OverlapPercent', 75);

imagesc(ax, tt, f, 10*log10(s + eps)); %En dB (eps evita log10(0))
axis(ax, 'xy');                        %Frecuencias bajas abajo
axis(ax, 'tight');
cb = colorbar(ax);
cb.Label.String = 'Potencia [dB]';
xlabel(ax, 'Tiempo [s]');
ylabel(ax, 'Frecuencia [Hz]');
end