function dibujarEspectro(ax, x, sps)
%DIBUJARESPECTRO Dibuja el espectro de potencia de una señal en un eje dado.
%   dibujarEspectro(ax, x, sps) calcula el espectro con pspectrum y lo
%   pinta en dB en el eje ax. Es la versión "con eje" de pspectrum(x, sps),
%   que sin salidas siempre dibuja en el eje actual y no sirve en una app.
%
%   Entradas:
%     ax  - eje donde dibujar (subplot o uiaxes)
%     x   - señal (vector) [uV]
%     sps - frecuencia de muestreo [Hz]
%
%   Ejemplo (dos espectros superpuestos):
%     dibujarEspectro(ax, res.v0, p.sps);
%     hold(ax, 'on');
%     dibujarEspectro(ax, res.v0notch, p.sps);
%     legend(ax, 'Original', 'Notch');
%
%   Nota: no hace hold on ni pone título; eso lo decide quien la llama.

[pw, f] = pspectrum(x, sps);        %Potencia (lineal) y frecuencias [Hz]
plot(ax, f, 10*log10(pw));          %Pasamos a dB, como hace pspectrum
grid(ax, 'on');
xlabel(ax, 'Frecuencia [Hz]');
ylabel(ax, 'Potencia [dB]');
end