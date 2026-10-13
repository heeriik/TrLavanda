"""Código SIC de la SEC -> sector amplio (aproximación a los 11 sectores GICS).

Comparamos empresas DENTRO de su sector porque los ratios "normales" cambian mucho entre
sectores: un banco no tiene margen bruto, una eléctrica siempre tiene mucha deuda, una
empresa de software tiene márgenes del 70 %. Sin esta corrección, el ranking acabaría
eligiendo sectores enteros en vez de las mejores empresas de cada uno.
"""

# (desde, hasta, sector). Se evalúan en orden: el primer rango que encaja gana.
SIC_RANGES: list[tuple[int, int, str]] = [
    (1311, 1389, "Energy"),
    (2900, 2999, "Energy"),
    (1000, 1499, "Materials"),
    (1530, 1531, "Consumer Discretionary"),  # promotoras de viviendas
    (1500, 1799, "Industrials"),
    (2000, 2199, "Consumer Staples"),
    (2200, 2399, "Consumer Discretionary"),
    (2700, 2799, "Communication Services"),
    (2830, 2839, "Health Care"),  # farmacéuticas y biotecnología
    (2840, 2844, "Consumer Staples"),  # cosmética y limpieza
    (2400, 3399, "Materials"),
    (3570, 3579, "Information Technology"),  # ordenadores
    (3630, 3639, "Consumer Discretionary"),  # electrodomésticos
    (3640, 3699, "Information Technology"),  # semiconductores, electrónica, telecom
    (3400, 3629, "Industrials"),
    (3710, 3716, "Consumer Discretionary"),  # automóviles
    (3700, 3799, "Industrials"),
    (3840, 3851, "Health Care"),  # material médico
    (3800, 3899, "Information Technology"),  # instrumentos de medida
    (3900, 3999, "Consumer Discretionary"),
    (4700, 4700, "Consumer Discretionary"),  # agencias de viajes online
    (4000, 4799, "Industrials"),
    (4800, 4899, "Communication Services"),
    (4922, 4923, "Energy"),  # gasoductos
    (4950, 4959, "Industrials"),  # residuos
    (4900, 4999, "Utilities"),
    (5120, 5122, "Health Care"),  # distribución farmacéutica
    (5140, 5149, "Consumer Staples"),
    (5000, 5199, "Industrials"),
    (5310, 5331, "Consumer Staples"),  # grandes superficies
    (5400, 5499, "Consumer Staples"),  # supermercados
    (5912, 5912, "Consumer Staples"),  # farmacias
    (5200, 5999, "Consumer Discretionary"),
    (6798, 6798, "Real Estate"),  # REIT
    (6500, 6599, "Real Estate"),
    (6000, 6799, "Financials"),
    (7370, 7379, "Information Technology"),  # software y servicios informáticos
    (7800, 7999, "Communication Services"),  # entretenimiento
    (7000, 7299, "Consumer Discretionary"),
    (7300, 7399, "Industrials"),
    (8000, 8099, "Health Care"),
    (8731, 8731, "Health Care"),  # investigación biológica (biotecnológicas)
    (100, 999, "Consumer Staples"),
    (7500, 8999, "Industrials"),
]


def sic_to_sector(sic: int | None) -> str:
    if sic is None:
        return "Unknown"
    for lo, hi, sector in SIC_RANGES:
        if lo <= sic <= hi:
            return sector
    return "Unknown"
