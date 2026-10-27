function destino = guardarFiguras(carpetaFiguras, archivo, figs)
%GUARDARFIGURAS Guarda figuras como PNG.
%   destino = guardarFiguras(carpetaDestino, archivo) crea la subcarpeta
%   carpetaDestino\<nombre de la muestra> (el nombre del CSV sin
%   extensión) y exporta en ella cada figura abierta como figura_N.png,
%   a 200 ppp. Si la subcarpeta no existe, la crea.
%
%   destino = guardarFiguras(carpetaDestino, archivo, figs) guarda solo
%   las figuras de figs (p.ej. las ocultas de crearFiguras), numeradas
%   1, 2, 3... en el orden del vector. Es lo que usa la app.
%
%   Entradas:
%     carpetaDestino - carpeta raíz de resultados (string)
%     archivo        - nombre del CSV analizado (de elegirMuestra)
%     figs           - (opcional) vector de figuras a guardar. Si no se
%                      pasa, guarda todas las figuras abiertas
%   Salida:
%     destino - ruta de la subcarpeta de la muestra, para usarla al
%               guardar el resto de resultados
%
%   Nota: sobrescribe los PNG si la muestra ya se había analizado.
%
%   Ejemplo:
%     destino = guardarFiguras("C:\...\processed\OutputAnalisis", archivo);
%     destino = guardarFiguras(carpetaDestino, archivo, crearFiguras(res,'off'));
    [~, nombreMuestra] = fileparts(archivo);
    destino = fullfile(carpetaFiguras, nombreMuestra);
    if ~exist(destino, 'dir'), mkdir(destino); end
    if nargin < 3                       %Sin lista: todas las abiertas (script)
        figs = findobj('Type','figure');
        numeros = [figs.Number];        %Número de cada figura (Figure 1, 2...)
    else                                %Con lista: en el orden recibido (app)
        numeros = 1:numel(figs);
    end
    for k = 1:numel(figs)
        exportgraphics(figs(k), fullfile(destino, "figura_" + numeros(k) + ".png"), 'Resolution', 200);
    end
    fprintf('%d figuras guardadas en %s\n', numel(figs), destino);
end