clear; clc;

s = serialport("COM8", 115200);
configureTerminator(s, "CR/LF");
s.Timeout = 2;                      % si en 2 s no llega nada, readline devuelve vacío
flush(s);

duracion = 20;                      % segundos a grabar
datos = [];
vacias = 0;

tic;
while toc < duracion
    linea = readline(s);
    if isempty(linea)               % no llegó nada en 2 s
        vacias = vacias + 1;
        disp('Sin datos (timeout)');
        continue;
    end
    v = sscanf(linea, '%d %d');
    if numel(v) == 2                % solo líneas con dos números
        datos(end+1, :) = v';
    end
end
clear s;                            % cierra el puerto

writematrix(datos, "22.10.antebrazoLuegoBicep.csv");
fprintf('%d muestras = %.1f s a 500 Hz (%d timeouts)\n', ...
    size(datos,1), size(datos,1)/500, vacias);