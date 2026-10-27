function avisos = validarParametros(p, nMuestras)
%VALIDARPARAMETROS Comprueba que los parámetros del análisis tienen sentido.
%   avisos = validarParametros(p, nMuestras) revisa el struct p antes de
%   analizar. Hay dos tipos de problema:
%     - Errores: con ese valor el análisis no se puede hacer o daría
%       resultados sin sentido (p.ej. corte superior por encima de
%       Nyquist). Se lanza error() con un mensaje claro y el análisis se
%       para. En la app lo muestra el try/catch de Analizar.
%     - Avisos: el análisis se puede hacer, pero conviene revisarlo
%       (p.ej. corte superior por encima de lo que deja pasar el ADS).
%       Se devuelven en avisos para que quien llame decida cómo
%       enseñarlos.
%
%   Entradas:
%     p         - struct de parámetros (el mismo que recibe analizarEMG)
%     nMuestras - número de muestras de la señal, para conocer su
%                 duración (nMuestras / p.sps)
%   Salida:
%     avisos - cell array de textos, uno por aviso ({} si todo está bien)
%
%   Ejemplo:
%     avisos = validarParametros(p, numel(ch0));
%     for k = 1:numel(avisos), fprintf('AVISO: %s\n', avisos{k}); end
%
%   Nota: 0.262·sps es el corte a -3 dB del filtro sinc interno del
%   ADS1198 (unos 131 Hz a 500 SPS). Por encima, la señal ya llega
%   atenuada aunque el paso banda la deje pasar.

avisos = {};

%Datos del ADC
if p.sps <= 0
    error('validarParametros:sps', 'Samples/s tiene que ser mayor que 0.');
end
if p.ganancia <= 0 || p.vRef <= 0
    error('validarParametros:adc', 'La ganancia y Vref tienen que ser mayores que 0.');
end
if p.nBitsADC <= 0 || mod(p.nBitsADC, 1) ~= 0
    error('validarParametros:bits', 'Los bits del ADC tienen que ser un número entero mayor que 0.');
end

fNyquist = p.sps/2;              %Máxima frecuencia que se puede ver
duracion = nMuestras / p.sps;    %Duración de la señal [s]

%Notch
if p.notchOn
    if p.f0 <= 0 || p.f0 >= fNyquist
        error('validarParametros:f0', ...
            'La frecuencia del notch (%g Hz) tiene que estar entre 0 y %g Hz (sps/2).', p.f0, fNyquist);
    end
    if p.Q <= 0
        error('validarParametros:Q', 'El factor de calidad Q tiene que ser mayor que 0.');
    end
end

%Paso banda
if p.bandaOn
    if p.fBanda(1) <= 0 || p.fBanda(1) >= p.fBanda(2)
        error('validarParametros:fBanda', ...
            'El corte inferior (%g Hz) tiene que ser mayor que 0 y menor que el superior (%g Hz).', ...
            p.fBanda(1), p.fBanda(2));
    end
    if p.fBanda(2) >= fNyquist
        error('validarParametros:nyquist', ...
            'El corte superior (%g Hz) tiene que ser menor que %g Hz (sps/2).', p.fBanda(2), fNyquist);
    end
    if p.fBanda(2) > 0.262*p.sps
        avisos{end+1} = sprintf(['El corte superior (%g Hz) supera el ancho de banda real ' ...
            'del ADS a %g SPS (~%.0f Hz).\n\n' ...
            'El ADS lleva un filtro interno que atenúa todo lo que pase de ~%.0f Hz, así que ' ...
            'entre %.0f y %g Hz la señal ya llega debilitada y el paso banda no la recupera.\n\n' ...
            'Para que el corte sea real, baja el corte superior a %.0f Hz o menos, o sube los SPS del ADS.'], ...
            p.fBanda(2), p.sps, 0.262*p.sps, 0.262*p.sps, 0.262*p.sps, p.fBanda(2), floor(0.262*p.sps));
    end
end

%Envolvente RMS y umbral
if p.tRMS*p.sps < 1 || p.tRMS >= duracion
    error('validarParametros:tRMS', ...
        'El suavizado (%g s) tiene que durar al menos 1 muestra y menos que la señal (%.1f s).', ...
        p.tRMS, duracion);
end
if p.tReposo(1) < 0 || p.tReposo(1) >= p.tReposo(2) || p.tReposo(2) > duracion
    error('validarParametros:tReposo', ...
        'La franja de reposo (%g a %g s) tiene que estar dentro de la señal (0 a %.1f s) y "desde" ser menor que "hasta".', ...
        p.tReposo(1), p.tReposo(2), duracion);
end
if p.kUmbral < 0
    error('validarParametros:k', 'La sensibilidad K no puede ser negativa.');
end

%Espectrograma
if p.tVentana <= 0 || p.tVentana >= duracion
    error('validarParametros:tVentana', ...
        'La ventana del espectrograma (%g s) tiene que ser mayor que 0 y menor que la señal (%.1f s).', ...
        p.tVentana, duracion);
end
end