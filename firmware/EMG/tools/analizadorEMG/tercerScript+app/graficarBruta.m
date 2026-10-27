function graficarBruta(res, ax)
%GRAFICARBRUTA Dibuja la señal bruta centrada de los dos canales.
%   graficarBruta(res, ax) pinta res.v0 en ax(1) y res.v1 en ax(2) frente
%   al tiempo res.t. Borra lo que hubiera antes en esos ejes.
%
%   Entradas:
%     res - struct de resultados de analizarEMG (usa t, v0, v1)
%     ax  - vector de 2 ejes [eje canal 0, eje canal 1]. Pueden ser
%           subplots de una figure (script) o uiaxes (app)
%
%   Ejemplo (script):
%     figure
%     ax = [subplot(2,1,1), subplot(2,1,2)];
%     graficarBruta(res, ax);
%
%   Ejemplo (app):
%     graficarBruta(res, [app.EjeCanal0, app.EjeCanal1]);
%
%   Nota: cada orden lleva el eje como primer argumento (plot(ax(1),...))
%   para no depender de la figura actual; así funciona igual en la app.

%Canal 0
plot(ax(1), res.t, res.v0);
grid(ax(1), 'on');
ylabel(ax(1), 'Canal 0 [\muV]');
title(ax(1), 'Señal bruta centrada');

%Canal 1
plot(ax(2), res.t, res.v1);
grid(ax(2), 'on');
xlabel(ax(2), 'Tiempo [s]');
ylabel(ax(2), 'Canal 1 [\muV]');
title(ax(2), 'Señal bruta centrada');
end