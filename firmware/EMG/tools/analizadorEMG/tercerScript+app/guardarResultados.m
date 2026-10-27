function guardarResultados(destino, resultados)
%GUARDARRESULTADOS Guarda la tabla de resultados de una muestra.
%   guardarResultados(destino, resultados) escribe, dentro de la
%   subcarpeta de la muestra:
%     destino\resultados.csv        - último análisis (sobrescribe)
%     destino\resumen_muestras.csv  - añade una fila por cada vez que
%                                     se guarda esta muestra (historial)
%   La cabecera del resumen solo se escribe la primera vez.
%
%   Entradas:
%     destino    - subcarpeta de la muestra (de guardarFiguras)
%     resultados - tabla de 1 fila con los valores del análisis
%
%   Nota: si se guarda dos veces la misma muestra (p.ej. con otro tRMS),
%   el resumen tendrá dos filas; la columna tRMS_s ayuda a distinguirlas.
%
%   Ejemplo:
%     guardarResultados(destino, resultados);
writetable(resultados, fullfile(destino, "resultados.csv"));
writetable(resultados, fullfile(destino, "resumen_muestras.csv"), 'WriteMode', 'append');
end