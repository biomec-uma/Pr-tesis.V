function graficarNotch(res, ax)
%GRAFICARNOTCH Compara el espectro antes y después del filtro notch.
%   graficarNotch(res, ax) superpone, para cada canal, el espectro de la
%   señal bruta y el de la señal tras el notch. Sirve para comprobar que
%   el pico de la red (p.f0) desaparece sin tocar el resto del espectro.
%
%   Entradas:
%     res - struct de resultados de analizarEMG (usa v0, v1, v0notch,
%           v1notch y p.sps)
%     ax  - vector de 2 ejes [eje canal 0, eje canal 1]. Pueden ser
%           subplots de una figure (script) o uiaxes (app)
%
%   Ejemplo (script):
%     figure
%     ax = [subplot(2,1,1), subplot(2,1,2)];
%     graficarNotch(res, ax);
%
%   Nota: usa dibujarEspectro. Si p.notchOn = false, las dos curvas
%   salen iguales (la señal no se ha filtrado).

%Canal 0
dibujarEspectro(ax(1), res.v0, res.p.sps);
hold(ax(1), 'on');                          %Para superponer la 2ª curva
dibujarEspectro(ax(1), res.v0notch, res.p.sps);
hold(ax(1), 'off');                         %Así la próxima vez se borra
legend(ax(1), 'Original', 'Notch');
title(ax(1), 'Canal 0');

%Canal 1
dibujarEspectro(ax(2), res.v1, res.p.sps);
hold(ax(2), 'on');
dibujarEspectro(ax(2), res.v1notch, res.p.sps);
hold(ax(2), 'off');
legend(ax(2), 'Original', 'Notch');
title(ax(2), 'Canal 1');
end
