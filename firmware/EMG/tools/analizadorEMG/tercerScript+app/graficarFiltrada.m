function graficarFiltrada(res, ax)
%GRAFICARFILTRADA Compara en el tiempo la señal bruta y la filtrada.
%   graficarFiltrada(res, ax) superpone, para cada canal, la señal bruta
%   centrada y la señal tras notch + paso banda. Sirve para ver cuánto
%   ruido (deriva, 50 Hz) quitan los filtros y si las ráfagas EMG siguen ahí.
%
%   Entradas:
%     res - struct de resultados de analizarEMG (usa t, v0, v1,
%           v0fBanda, v1fBanda)
%     ax  - vector de 2 ejes [eje canal 0, eje canal 1]. Pueden ser
%           subplots de una figure (script) o uiaxes (app)
%
%   Ejemplo (script):
%     figure
%     ax = [subplot(2,1,1), subplot(2,1,2)];
%     graficarFiltrada(res, ax);
%
%   Nota: "Filtrada" es la salida de todos los filtros activos; si
%   p.notchOn y p.bandaOn son false, las dos curvas coinciden.

%Canal 0
plot(ax(1), res.t, res.v0);
hold(ax(1), 'on');                          %Para superponer la 2ª curva
plot(ax(1), res.t, res.v0fBanda);
hold(ax(1), 'off');                         %Así la próxima vez se borra
grid(ax(1), 'on');
legend(ax(1), 'Bruta', 'Filtrada');
ylabel(ax(1), 'Canal 0 [\muV]');
title(ax(1), 'Señal bruta vs filtrada');

%Canal 1
plot(ax(2), res.t, res.v1);
hold(ax(2), 'on');
plot(ax(2), res.t, res.v1fBanda);
hold(ax(2), 'off');
grid(ax(2), 'on');
legend(ax(2), 'Bruta', 'Filtrada');
xlabel(ax(2), 'Tiempo [s]');
ylabel(ax(2), 'Canal 1 [\muV]');
end