function figs = crearFiguras(res, visible)
%CREARFIGURAS Crea las 7 figuras del análisis, una por vista.
%   figs = crearFiguras(res, visible) abre 7 figuras con dos subplots
%   (canal 0 arriba, canal 1 abajo) y dibuja en cada una su gráfica,
%   en el mismo orden que el desplegable de la app (el camino que
%   recorre la señal):
%     1 Señal bruta            5 Bruta vs filtrada
%     2 Espectro               6 Espectrograma
%     3 Notch (antes/después)  7 Envolvente RMS y umbral
%     4 Paso banda (antes/después)
%
%   Entradas:
%     res     - struct de resultados de analizarEMG
%     visible - 'on' para verlas en pantalla (script, botón "Abrir
%               todas") u 'off' para crearlas ocultas (app, al guardar).
%               Opcional, por defecto 'on'
%   Salida:
%     figs - vector con las 7 figuras, en el orden de arriba. Sirve para
%            pasárselas a guardarFiguras y para cerrarlas después
%
%   Ejemplo (app):
%     figs = crearFiguras(app.res, 'off');
%     destino = guardarAnalisis(app.res, app.archivo, carpetaDestino, figs);
%     close(figs);
%
%   Nota: cada figura lleva en 'Name' el nombre de su vista, para
%   reconocerla en la barra de título.

if nargin < 2
    visible = 'on';
end

%Nombre y función de dibujo de cada vista (mismo orden que VistaDropDown)
vistas = {
    'Señal bruta',                @graficarBruta
    'Espectro',                   @graficarEspectro
    'Notch (antes/después)',      @graficarNotch
    'Paso banda (antes/después)', @graficarBanda
    'Bruta vs filtrada',          @graficarFiltrada
    'Espectrograma',              @graficarEspectrograma
    'Envolvente RMS y umbral',    @graficarEnvolvente};

nVistas = size(vistas, 1);
figs = gobjects(1, nVistas);        %Vector vacío de figuras
for k = 1:nVistas
    figs(k) = figure('Name', vistas{k,1}, 'Visible', visible);
    ax = [subplot(2,1,1, 'Parent', figs(k)), subplot(2,1,2, 'Parent', figs(k))];
    vistas{k,2}(res, ax);           %Llama a graficarX(res, ax)
end
end