function graficarEspectro(res, ax)
%GRAFICARESPECTRO Dibuja el espectro de la señal bruta de los dos canales.
%   graficarEspectro(res, ax) pinta el espectro de potencia de res.v0 en
%   ax(1) y el de res.v1 en ax(2). Sirve para ver cuánto pesa el pico de
%   la red (50 Hz) antes de filtrar.
%
%   Entradas:
%     res - struct de resultados de analizarEMG (usa v0, v1 y p.sps)
%     ax  - vector de 2 ejes [eje canal 0, eje canal 1]. Pueden ser
%           subplots de una figure (script) o uiaxes (app)
%
%   Ejemplo (script):
%     figure
%     ax = [subplot(2,1,1), subplot(2,1,2)];
%     graficarEspectro(res, ax);
%
%   Nota: usa dibujarEspectro, que debe estar en la misma carpeta.

%Canal 0
dibujarEspectro(ax(1), res.v0, res.p.sps);
title(ax(1), 'Canal 0');

%Canal 1
dibujarEspectro(ax(2), res.v1, res.p.sps);
title(ax(2), 'Canal 1');
end