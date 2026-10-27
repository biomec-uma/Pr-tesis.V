function [archivo, carpeta] = elegirMuestra(carpetaInicial)
%ELEGIRMUESTRA Abre el explorador para seleccionar un CSV de EMG.
%   [archivo, carpeta] = elegirMuestra(carpetaInicial) abre una ventana
%   de selección de archivos en carpetaInicial, filtrando por *.csv.
%
%   Entradas:
%     carpetaInicial - ruta donde se abre el explorador (string)
%   Salidas:
%     archivo - nombre del CSV elegido, con extensión (p.ej. "20.10.csv")
%     carpeta - ruta de la carpeta que lo contiene
%
%   Si se cierra la ventana sin elegir nada, detiene el script con error.
%
%   Ejemplo:
%     [archivo, carpeta] = elegirMuestra("C:\...\data\raw");
%     data = readtable(fullfile(carpeta, archivo));
[archivo, carpeta] = uigetfile("*.csv", "Elige la muestra EMG", carpetaInicial);
if isequal(archivo, 0)
    error("No elegiste ningún archivo");
end
end