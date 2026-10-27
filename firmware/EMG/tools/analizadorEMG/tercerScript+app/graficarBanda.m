function graficarBanda(res, ax)
%GRAFICARBANDA Compara el espectro antes y después del paso banda.
%   graficarBanda(res, ax) superpone, para cada canal, el espectro de la
%   señal con solo el notch y el de la señal con notch + paso banda.
%   Sirve para comprobar que el filtro corta fuera de p.fBanda (deriva
%   por debajo y ruido por encima) sin tocar la banda útil del EMG.
%
%   Entradas:
%     res - struct de resultados de analizarEMG (usa v0notch, v1notch,
%           v0fBanda, v1fBanda y p.sps)
%     ax  - vector de 2 ejes [eje canal 0, eje canal 1]. Pueden ser
%           subplots de una figure (script) o uiaxes (app)
%
%   Ejemplo (script):
%     figure
%     ax = [subplot(2,1,1), subplot(2,1,2)];
%     graficarBanda(res, ax);
%
%   Nota: usa dibujarEspectro. Si p.bandaOn = false, las dos curvas
%   salen iguales (la señal no se ha filtrado).

%Canal 0
dibujarEspectro(ax(1), res.v0notch, res.p.sps);
hold(ax(1), 'on');                          %Para superponer la 2ª curva
dibujarEspectro(ax(1), res.v0fBanda, res.p.sps);
hold(ax(1), 'off');                         %Así la próxima vez se borra
legend(ax(1), 'Solo notch', 'Notch + paso banda');
title(ax(1), 'Canal 0');

%Canal 1
dibujarEspectro(ax(2), res.v1notch, res.p.sps);
hold(ax(2), 'on');
dibujarEspectro(ax(2), res.v1fBanda, res.p.sps);
hold(ax(2), 'off');
legend(ax(2), 'Solo notch', 'Notch + paso banda');
title(ax(2), 'Canal 1');
end