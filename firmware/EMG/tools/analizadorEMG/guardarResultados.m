function guardarResultados(destino, carpetaFiguras, resultados)
%GUARDARRESULTADOS Guarda la tabla de resultados de una muestra.
%   guardarResultados(destino, carpetaDestino, resultados) escribe:
%     destino\resultados.csv               - solo esta muestra (sobrescribe)
%     carpetaDestino\resumen_muestras.csv  - añade una fila al resumen
%                                            de todas las muestras
%   La cabecera del resumen solo se escribe la primera vez.
%
%   Entradas:
%     destino        - subcarpeta de la muestra (de guardarFiguras)
%     carpetaDestino - carpeta raíz de resultados
%     resultados     - tabla de 1 fila con los valores del análisis
%
%   Nota: si se analiza dos veces la misma muestra, el resumen tendrá
%   dos filas; la columna tRMS_s ayuda a distinguirlas.
%
%   Ejemplo:
%     guardarResultados(destino, carpetaDestino, resultados);
writetable(resultados, fullfile(destino, "resultados.csv"));
writetable(resultados, fullfile(carpetaFiguras, "resumen_muestras.csv"), 'WriteMode', 'append');
end