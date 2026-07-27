"""Statistische Kernfunktionen der Fähigkeits- und Diskretisierungsbewertung."""
from __future__ import annotations

from dataclasses import dataclass
import math
import warnings
from typing import Callable, Sequence

import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr
from scipy.stats import beta, chi2, jarque_bera, norm, shapiro, t


@dataclass(frozen=True)
class DescriptiveStats:
    n: int
    mean: float
    stdev: float
    minimum: float
    maximum: float
    span: float
    unique_levels: int


@dataclass(frozen=True)
class QuantizedFit:
    mu: float
    sigma: float
    levels: np.ndarray
    counts: np.ndarray
    success: bool
    message: str
    objective: float




@dataclass(frozen=True)
class CapabilityIntervals:
    """Konfidenzintervalle und einseitige Untergrenzen für Fähigkeitskennwerte.

    C_m wird unter Normalverteilungsannahme exakt über die Chi-Quadrat-Verteilung
    der Stichprobenvarianz behandelt. Für C_mk wird die in professioneller
    Fähigkeitssoftware verbreitete Bissell-/Delta-Approximation verwendet.
    """

    confidence_level: float
    cm_lower: float | None
    cm_upper: float | None
    cm_lower_one_sided: float | None
    cmk_lower: float | None
    cmk_upper: float | None
    cmk_lower_one_sided: float | None
    mean_lower: float | None
    mean_upper: float | None
    stdev_lower: float | None
    stdev_upper: float | None
    cml: float | None
    cmu: float | None
    limiting_side: str | None
    method_cm: str
    method_cmk: str


@dataclass(frozen=True)
class BinomialPpmInterval:
    """Exaktes Clopper-Pearson-Intervall für einen beobachteten ppm-Anteil."""

    confidence_level: float
    lower_ppm: float
    upper_ppm: float
    upper_one_sided_ppm: float


@dataclass(frozen=True)
class PpmPerformance:
    """Beobachtete und normalmodellbasierte Grenzüberschreitungsanteile."""

    observed_below_count: int
    observed_above_count: int
    observed_ppm_below: float
    observed_ppm_above: float
    observed_ppm_total: float
    expected_ppm_below: float | None
    expected_ppm_above: float | None
    expected_ppm_total: float | None
    observed_total_ci_lower: float
    observed_total_ci_upper: float
    observed_total_upper_one_sided: float


def descriptive(values: Sequence[float]) -> DescriptiveStats:
    array = np.asarray(values, dtype=float)
    if array.size == 0:
        raise ValueError("Die Messreihe ist leer.")
    if not np.all(np.isfinite(array)):
        raise ValueError("Die Messreihe enthält nicht-endliche Werte.")
    n = int(array.size)
    mean = float(np.mean(array))
    stdev = float(np.std(array, ddof=1)) if n >= 2 else 0.0
    minimum = float(np.min(array))
    maximum = float(np.max(array))
    return DescriptiveStats(n, mean, stdev, minimum, maximum, maximum - minimum, int(np.unique(array).size))


def capability_indices(mean: float, stdev: float, lower_limit: float, upper_limit: float) -> tuple[float | None, float | None]:
    """Berechnet Cₘ und Cₘₖ. Bei s <= 0 bleiben beide Kennwerte undefiniert."""
    if lower_limit >= upper_limit:
        raise ValueError("Die untere Grenze muss kleiner als die obere Grenze sein.")
    if stdev <= 0:
        return None, None
    cm = (upper_limit - lower_limit) / (6.0 * stdev)
    cmk = min((upper_limit - mean) / (3.0 * stdev), (mean - lower_limit) / (3.0 * stdev))
    return float(cm), float(cmk)


def binomial_ppm_interval(successes: int, trials: int, confidence_level: float = 0.95) -> BinomialPpmInterval:
    """Exaktes zweiseitiges Clopper-Pearson-Intervall plus einseitige Obergrenze.

    Die Skalierung auf ppm ändert nur die Einheit. Das Intervall beschreibt die
    Unsicherheit des beobachteten Anteils und benötigt keine Normalverteilungsannahme.
    """
    if trials < 1:
        raise ValueError("Die Zahl der Beobachtungen muss positiv sein.")
    if not 0 <= successes <= trials:
        raise ValueError("Die Zahl der Grenzüberschreitungen ist ungültig.")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("Das Konfidenzniveau muss zwischen 0 und 1 liegen.")
    alpha = 1.0 - confidence_level
    lower = 0.0 if successes == 0 else float(beta.ppf(alpha / 2.0, successes, trials - successes + 1))
    upper = 1.0 if successes == trials else float(beta.ppf(1.0 - alpha / 2.0, successes + 1, trials - successes))
    upper_one = 1.0 if successes == trials else float(beta.ppf(confidence_level, successes + 1, trials - successes))
    return BinomialPpmInterval(
        confidence_level=confidence_level,
        lower_ppm=lower * 1_000_000.0,
        upper_ppm=upper * 1_000_000.0,
        upper_one_sided_ppm=upper_one * 1_000_000.0,
    )


def capability_confidence_intervals(
    mean: float,
    stdev: float,
    n: int,
    lower_limit: float,
    upper_limit: float,
    *,
    confidence_level: float = 0.95,
    sigma_tolerance: float = 6.0,
) -> CapabilityIntervals:
    """Berechnet typische Unsicherheitsangaben einer Normal-Capability-Analyse.

    * C_m: exaktes Intervall aus der Chi-Quadrat-Verteilung der Varianz.
    * C_mk: Bissell-/Delta-Approximation
      SE = sqrt(4/(K² n) + C_mk²/(2(n-1))).
    * Mittelwert: t-Intervall.
    * Standardabweichung: exaktes Chi-Quadrat-Intervall.

    Zusätzlich werden die einseitigen Komponenten zur unteren und oberen Grenze
    sowie die für eine Freigabelogik besonders nützlichen einseitigen unteren
    Konfidenzgrenzen ausgegeben.
    """
    if lower_limit >= upper_limit:
        raise ValueError("Die untere Grenze muss kleiner als die obere Grenze sein.")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("Das Konfidenzniveau muss zwischen 0 und 1 liegen.")
    if sigma_tolerance <= 0:
        raise ValueError("Die Sigma-Toleranz muss positiv sein.")
    if n < 2 or stdev <= 0 or not math.isfinite(stdev):
        return CapabilityIntervals(
            confidence_level, None, None, None, None, None, None, None, None, None, None,
            None, None, None,
            "Chi-Quadrat (Normalmodell)",
            "Bissell-/Delta-Approximation (Normalmodell)",
        )

    alpha = 1.0 - confidence_level
    df = n - 1
    cm, cmk = capability_indices(mean, stdev, lower_limit, upper_limit)
    assert cm is not None and cmk is not None

    cm_lower = cm * math.sqrt(float(chi2.ppf(alpha / 2.0, df)) / df)
    cm_upper = cm * math.sqrt(float(chi2.ppf(1.0 - alpha / 2.0, df)) / df)
    cm_lower_one = cm * math.sqrt(float(chi2.ppf(alpha, df)) / df)

    z_two = float(norm.ppf(1.0 - alpha / 2.0))
    z_one = float(norm.ppf(confidence_level))
    cmk_se = math.sqrt(4.0 / (sigma_tolerance * sigma_tolerance * n) + (cmk * cmk) / (2.0 * df))
    cmk_lower = cmk - z_two * cmk_se
    cmk_upper = cmk + z_two * cmk_se
    cmk_lower_one = cmk - z_one * cmk_se

    t_value = float(t.ppf(1.0 - alpha / 2.0, df))
    mean_half = t_value * stdev / math.sqrt(n)
    mean_lower = mean - mean_half
    mean_upper = mean + mean_half
    stdev_lower = math.sqrt(df * stdev * stdev / float(chi2.ppf(1.0 - alpha / 2.0, df)))
    stdev_upper = math.sqrt(df * stdev * stdev / float(chi2.ppf(alpha / 2.0, df)))

    cml = (mean - lower_limit) / (3.0 * stdev)
    cmu = (upper_limit - mean) / (3.0 * stdev)
    limiting_side = "USG / UGW" if cml <= cmu else "OSG / OGW"

    return CapabilityIntervals(
        confidence_level=confidence_level,
        cm_lower=float(cm_lower),
        cm_upper=float(cm_upper),
        cm_lower_one_sided=float(cm_lower_one),
        cmk_lower=float(cmk_lower),
        cmk_upper=float(cmk_upper),
        cmk_lower_one_sided=float(cmk_lower_one),
        mean_lower=float(mean_lower),
        mean_upper=float(mean_upper),
        stdev_lower=float(stdev_lower),
        stdev_upper=float(stdev_upper),
        cml=float(cml),
        cmu=float(cmu),
        limiting_side=limiting_side,
        method_cm="Chi-Quadrat (Normalmodell)",
        method_cmk="Bissell-/Delta-Approximation (Normalmodell)",
    )


def ppm_performance(
    values: Sequence[float],
    lower_limit: float,
    upper_limit: float,
    *,
    mean: float | None = None,
    stdev: float | None = None,
    confidence_level: float = 0.95,
) -> PpmPerformance:
    """Berechnet beobachtete und ergänzend normalmodellbasierte ppm-Anteile.

    Beobachtete ppm sind die Stichprobenanteile außerhalb der Grenzen, skaliert auf
    eine Million. Die Modellwerte verwenden eine Normalverteilung mit arithmetischem
    Mittelwert und Stichprobenstandardabweichung. Bei s <= 0 bleiben die Modellwerte
    undefiniert; aus identischen Ablesewerten wird keine künstliche Streuung erzeugt.
    """
    if lower_limit >= upper_limit:
        raise ValueError("Die untere Grenze muss kleiner als die obere Grenze sein.")
    array = np.asarray(values, dtype=float)
    if array.size == 0:
        raise ValueError("Die Messreihe ist leer.")
    below_count = int(np.count_nonzero(array < lower_limit))
    above_count = int(np.count_nonzero(array > upper_limit))
    factor = 1_000_000.0 / float(array.size)
    observed_below = below_count * factor
    observed_above = above_count * factor

    used_mean = float(np.mean(array)) if mean is None else float(mean)
    used_stdev = (float(np.std(array, ddof=1)) if array.size >= 2 else 0.0) if stdev is None else float(stdev)
    if used_stdev <= 0 or not math.isfinite(used_stdev):
        expected_below = expected_above = expected_total = None
    else:
        expected_below = float(ndtr((lower_limit - used_mean) / used_stdev) * 1_000_000.0)
        expected_above = float((1.0 - ndtr((upper_limit - used_mean) / used_stdev)) * 1_000_000.0)
        expected_below = min(max(expected_below, 0.0), 1_000_000.0)
        expected_above = min(max(expected_above, 0.0), 1_000_000.0)
        expected_total = min(expected_below + expected_above, 1_000_000.0)

    total_interval = binomial_ppm_interval(below_count + above_count, int(array.size), confidence_level)

    return PpmPerformance(
        observed_below_count=below_count,
        observed_above_count=above_count,
        observed_ppm_below=observed_below,
        observed_ppm_above=observed_above,
        observed_ppm_total=observed_below + observed_above,
        expected_ppm_below=expected_below,
        expected_ppm_above=expected_above,
        expected_ppm_total=expected_total,
        observed_total_ci_lower=total_interval.lower_ppm,
        observed_total_ci_upper=total_interval.upper_ppm,
        observed_total_upper_one_sided=total_interval.upper_one_sided_ppm,
    )


def normality_tests(values: Sequence[float]) -> tuple[float | None, float | None, float | None, float | None]:
    array = np.asarray(values, dtype=float)
    if array.size < 3 or float(np.std(array, ddof=1)) <= 0:
        return None, None, None, None
    sw = shapiro(array)
    jb = jarque_bera(array)
    return float(sw.statistic), float(sw.pvalue), float(jb.statistic), float(jb.pvalue)


def reading_level_indices(values: Sequence[float], resolution: float) -> np.ndarray:
    if resolution <= 0:
        raise ValueError("Der Ableseschritt muss größer als null sein.")
    return np.rint(np.asarray(values, dtype=float) / resolution).astype(np.int64)


def grouped_indices(values: Sequence[float], resolution: float) -> tuple[np.ndarray, np.ndarray]:
    indices = reading_level_indices(values, resolution)
    if indices.size == 0:
        raise ValueError("Die Messreihe ist leer.")
    low = int(indices.min())
    high = int(indices.max())
    index_levels = np.arange(low, high + 1, dtype=np.int64)
    counts = np.bincount(indices - low, minlength=index_levels.size).astype(float)
    return index_levels, counts


def grouped_levels(values: Sequence[float], resolution: float) -> tuple[np.ndarray, np.ndarray]:
    indices, counts = grouped_indices(values, resolution)
    return indices.astype(float) * resolution, counts


def class_probabilities(levels: np.ndarray, mu: float, sigma: float, resolution: float) -> np.ndarray:
    """Offene linke Randklasse, reguläre Stufen, offene rechte Randklasse."""
    if sigma <= 0 or not math.isfinite(sigma):
        raise ValueError("Sigma muss positiv und endlich sein.")
    lower_z = (levels - resolution / 2.0 - mu) / sigma
    upper_z = (levels + resolution / 2.0 - mu) / sigma
    regular = ndtr(upper_z) - ndtr(lower_z)
    left = ndtr((levels[0] - resolution / 2.0 - mu) / sigma)
    right = 1.0 - ndtr((levels[-1] + resolution / 2.0 - mu) / sigma)
    probabilities = np.concatenate(([left], regular, [right])).astype(float)
    probabilities = np.maximum(probabilities, 0.0)
    total = float(probabilities.sum())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("Ungültige Klassenwahrscheinlichkeiten.")
    return probabilities / total


def _grouped_sample_stats(levels: np.ndarray, counts: np.ndarray) -> tuple[int, float, float]:
    n = int(round(float(np.sum(counts))))
    mean = float(np.sum(levels * counts) / n)
    if n < 2:
        return n, mean, 0.0
    variance = float(np.sum(counts * (levels - mean) ** 2) / (n - 1))
    return n, mean, math.sqrt(max(0.0, variance))


def _fit_grouped_quantized_normal(
    levels: np.ndarray,
    counts: np.ndarray,
    resolution: float,
    *,
    robust: bool,
) -> QuantizedFit:
    n, sample_mean, sample_stdev = _grouped_sample_stats(levels, counts)
    if n < 2:
        return QuantizedFit(sample_mean, 0.0, levels, counts, False, "n < 2", math.inf)
    if sample_stdev <= 0:
        return QuantizedFit(sample_mean, 0.0, levels, counts, False, "s = 0", math.inf)

    min_sigma = max(resolution * 1e-4, 1e-10)
    observed_width = float(levels[-1] - levels[0] + resolution)
    max_sigma = max(observed_width * 20.0, resolution * 20.0)
    mu_low = float(levels[0] - 10.0 * resolution)
    mu_high = float(levels[-1] + 10.0 * resolution)
    observed_mask = counts > 0

    # Dimensionlose Parametrisierung vermeidet numerische Gradientenauslöschung bei
    # Messwerten um 20 mm und Änderungen im Bereich weniger Mikrometer.
    center = sample_mean

    def negative_log_likelihood(theta: np.ndarray) -> float:
        mu = center + float(theta[0]) * resolution
        sigma = resolution * math.exp(float(theta[1]))
        probabilities = class_probabilities(levels, mu, sigma, resolution)[1:-1]
        observed_probabilities = probabilities[observed_mask]
        if np.any(observed_probabilities <= 0) or not np.all(np.isfinite(observed_probabilities)):
            return 1e300
        return -float(np.sum(counts[observed_mask] * np.log(observed_probabilities)))

    starts = [(sample_mean, max(sample_stdev, resolution / 4.0))]
    if robust:
        cumulative = np.cumsum(counts)
        median_index = int(np.searchsorted(cumulative, n / 2.0, side="left"))
        starts.extend([
            (float(levels[median_index]), max(sample_stdev, resolution / 2.0)),
            (sample_mean, max(resolution, sample_stdev)),
        ])
    best = None
    offset_bounds = ((mu_low - center) / resolution, (mu_high - center) / resolution)
    log_sigma_bounds = (math.log(min_sigma / resolution), math.log(max_sigma / resolution))
    for start_mu, start_sigma in starts:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = minimize(
                negative_log_likelihood,
                x0=np.array([(start_mu - center) / resolution, math.log(start_sigma / resolution)], dtype=float),
                method="Powell",
                bounds=(offset_bounds, log_sigma_bounds),
                options={"maxiter": 400 if robust else 180, "ftol": 1e-11, "xtol": 1e-9},
            )
        if np.isfinite(result.fun) and (best is None or float(result.fun) < float(best.fun)):
            best = result
    if best is None:
        return QuantizedFit(sample_mean, sample_stdev, levels, counts, False, "keine endliche Lösung", math.inf)
    fitted_mu = center + float(best.x[0]) * resolution
    fitted_sigma = resolution * math.exp(float(best.x[1]))
    at_boundary = fitted_sigma <= min_sigma * 1.01 or fitted_sigma >= max_sigma / 1.01
    success = bool(best.success) and not at_boundary and math.isfinite(fitted_mu) and math.isfinite(fitted_sigma)
    message = str(best.message) if not at_boundary else "Sigma liegt an einer Optimierungsgrenze."
    return QuantizedFit(fitted_mu, fitted_sigma, levels, counts, success, message, float(best.fun))


def fit_quantized_normal(values: Sequence[float], resolution: float) -> QuantizedFit:
    levels, counts = grouped_levels(values, resolution)
    return _fit_grouped_quantized_normal(levels, counts, resolution, robust=True)


def _q_from_fit(n: int, fit: QuantizedFit, resolution: float) -> float:
    probabilities = class_probabilities(fit.levels, fit.mu, fit.sigma, resolution)
    observed = np.concatenate(([0.0], fit.counts, [0.0]))
    expected = float(n) * probabilities
    if np.any(expected <= 0) or not np.all(np.isfinite(expected)):
        raise RuntimeError("Nicht-positive erwartete Klassenhäufigkeit.")
    return float(np.sum((observed - expected) ** 2 / expected))


def pearson_like_q(values: Sequence[float], resolution: float, fit: QuantizedFit | None = None) -> tuple[float, QuantizedFit]:
    array = np.asarray(values, dtype=float)
    fitted = fit or fit_quantized_normal(array, resolution)
    if not fitted.success:
        raise RuntimeError(f"Parameterschätzung fehlgeschlagen: {fitted.message}")
    return _q_from_fit(int(array.size), fitted, resolution), fitted


def quantize(values: np.ndarray, resolution: float) -> np.ndarray:
    return np.rint(values / resolution) * resolution


def _q_for_count_pattern(count_pattern: tuple[int, ...], resolution: float) -> float:
    """Berechnet Q für ein verschiebungsinvariantes Klassenmuster."""
    counts = np.asarray(count_pattern, dtype=float)
    levels = np.arange(len(count_pattern), dtype=float) * resolution
    fit = _fit_grouped_quantized_normal(levels, counts, resolution, robust=False)
    if not fit.success:
        raise RuntimeError(f"Parameterschätzung fehlgeschlagen: {fit.message}")
    return _q_from_fit(int(np.sum(counts)), fit, resolution)


def quantized_normal_bootstrap(
    values: Sequence[float],
    resolution: float,
    *,
    repetitions: int = 10_000,
    seed: int = 20_260_716,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[float, float, QuantizedFit, int, tuple[float, ...]]:
    """Parametrischer Bootstrap des quantisierten Normalmodells.

    Jede künstliche Stichprobe wird quantisiert, erhält Klassen anhand ihres eigenen
    beobachteten Wertebereichs und wird erneut aus den gruppierten Häufigkeiten angepasst.
    Wiederkehrende Klassenmuster werden zwischengespeichert; dies ändert das Verfahren
    nicht, verkürzt aber die Rechenzeit erheblich.
    """
    array = np.asarray(values, dtype=float)
    if repetitions < 1:
        raise ValueError("Die Zahl der Bootstrap-Wiederholungen muss positiv sein.")
    observed_stats = descriptive(array)
    if observed_stats.stdev <= 0:
        raise ValueError("Bootstrap wird bei s = 0 nicht ausgewiesen.")
    if observed_stats.unique_levels < 3:
        raise ValueError("Bootstrap wird bei weniger als drei Ablesestufen nicht ausgewiesen.")

    q_observed, observed_fit = pearson_like_q(array, resolution)
    generator = np.random.default_rng(seed)
    at_least_as_large = 0
    successful = 0
    failed = 0
    attempts = 0
    max_attempts = repetitions + max(500, repetitions // 5)
    cache: dict[tuple[int, ...], float | None] = {}
    q_values: list[float] = []

    while successful < repetitions and attempts < max_attempts:
        attempts += 1
        continuous = generator.normal(observed_fit.mu, observed_fit.sigma, size=array.size)
        indices = np.rint(continuous / resolution).astype(np.int64)
        low = int(indices.min())
        pattern = tuple(int(x) for x in np.bincount(indices - low))
        if pattern in cache:
            q_simulated = cache[pattern]
            if q_simulated is None:
                failed += 1
                continue
        else:
            try:
                q_simulated = _q_for_count_pattern(pattern, resolution)
            except (RuntimeError, ValueError, FloatingPointError):
                cache[pattern] = None
                failed += 1
                continue
            cache[pattern] = q_simulated
        q_values.append(float(q_simulated))
        if q_simulated >= q_observed:
            at_least_as_large += 1
        successful += 1
        if progress and (successful == repetitions or successful % max(1, repetitions // 100) == 0):
            progress(successful, repetitions)

    if successful < repetitions:
        raise RuntimeError(
            f"Nur {successful} von {repetitions} Bootstrap-Läufen konnten zuverlässig angepasst werden "
            f"({failed} fehlgeschlagen)."
        )
    p_value = (1.0 + at_least_as_large) / (repetitions + 1.0)
    return float(p_value), q_observed, observed_fit, failed, tuple(q_values)
