#!/usr/bin/env python3


class MarketBreadthAnalytics:
    def analyze(self, breadth_data: dict[str, int | float]) -> dict[str, int | float]:
        """
        Compute market breadth metrics from advancers/decliners/unchanged counts.
        """
        adv = int(breadth_data.get("advancers", 0) or 0)
        dec = int(breadth_data.get("decliners", 0) or 0)
        unc = int(breadth_data.get("unchanged", 0) or 0)
        total = adv + dec + unc

        if total <= 0:
            return {
                "advancers": adv,
                "decliners": dec,
                "unchanged": unc,
                "breadth_score": 0.0,
                "adv_ratio": 0.0,
                "dec_ratio": 0.0,
                "total": total
            }

        score = (adv - dec) / total
        adv_ratio = adv / total
        dec_ratio = dec / total

        return {
            "advancers": adv,
            "decliners": dec,
            "unchanged": unc,
            "breadth_score": round(score, 4),
            "adv_ratio": round(adv_ratio, 4),
            "dec_ratio": round(dec_ratio, 4),
            "total": total
        }
