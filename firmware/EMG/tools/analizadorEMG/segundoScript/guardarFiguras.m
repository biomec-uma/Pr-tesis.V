function destino = guardarFiguras(carpetaFiguras, archivo)
%GUARDARFIGURAS Guarda todas las figuras abiertas como PNG.
%   destino = guardarFiguras(carpetaDestino, archivo) crea la subcarpeta
%   carpetaDestino\<nombre de la muestra> (el nombre del CSV sin
%   extensión) y exporta en ella cada figura abierta como figura_N.png,
%   a 200 ppp. Si la subcarpeta no existe, la crea.
%
%   Entradas:
%     carpetaDestino - carpeta raíz de resultados (string)
%     archivo        - nombre del CSV analizado (de elegirMuestra)
%   Salida:
%     destino - ruta de la subcarpeta de la muestra, para usarla al
%               guardar el resto de resultados
%
%   Nota: sobrescribe los PNG si la muestra ya se había analizado.
%
%   Ejemplo:
%     destino = guardarFiguras("C:\...\processed\OutputAnalisis", archivo);
    [~, nombreMuestra] = fileparts(archivo);
    destino = fullfile(carpetaFiguras, nombreMuestra);
    if ~exist(destino, 'dir'), mkdir(destino); end
    figs = findobj('Type','figure');
    for k = 1:numel(figs)
        exportgraphics(figs(k), fullfile(destino, "figura_" + figs(k).Number + ".png"), 'Resolution', 200);
    end
    fprintf('%d figuras guardadas en %s\n', numel(figs), destino);
end