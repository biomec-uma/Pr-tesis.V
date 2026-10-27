function graficarEnvolvente(res, ax)
%GRAFICARENVOLVENTE Dibuja la EMG filtrada, su envolvente RMS y el umbral.
%   graficarEnvolvente(res, ax) pinta, para cada canal, la señal filtrada
%   en gris, encima la envolvente RMS y una línea roja discontinua con el
%   umbral de activación. Sirve para ver si las contracciones superan el
%   umbral y el reposo queda por debajo.
%
%   Entradas:
%     res - struct de resultados de analizarEMG (usa t, v0fBanda,
%           v1fBanda, rms0, rms1, umbral0, umbral1)
%     ax  - vector de 2 ejes [eje canal 0, eje canal 1]. Pueden ser
%           subplots de una figure (script) o uiaxes (app)
%
%   Ejemplo (script):
%     figure
%     ax = [subplot(2,1,1), subplot(2,1,2)];
%     graficarEnvolvente(res, ax);
%
%   Nota: el umbral es media + p.kUmbral·std de la RMS en p.tReposo; si
%   cambias el tramo de reposo, vuelve a llamar a analizarEMG antes.

%Canal 0
plot(ax(1), res.t, res.v0fBanda, 'Color', [0.6 0.6 0.6]); %Señal en gris
hold(ax(1), 'on');                          %Para superponer RMS y umbral
plot(ax(1), res.t, res.rms0, 'LineWidth', 2);
yline(ax(1), res.umbral0, '--r', 'Umbral');
hold(ax(1), 'off');                         %Así la próxima vez se borra
grid(ax(1), 'on');
ylabel(ax(1), 'Canal 0 [\muV]');
title(ax(1), 'EMG Filtrado y envolvente RMS');

%Canal 1
plot(ax(2), res.t, res.v1fBanda, 'Color', [0.6 0.6 0.6]);
hold(ax(2), 'on');
plot(ax(2), res.t, res.rms1, 'LineWidth', 2);
yline(ax(2), res.umbral1, '--r', 'Umbral');
hold(ax(2), 'off');
grid(ax(2), 'on');
ylabel(ax(2), 'Canal 1 [\muV]');
xlabel(ax(2), 'Tiempo [s]');
end