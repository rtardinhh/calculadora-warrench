import json
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional


# -----------------------------
# Materials
# -----------------------------

MATERIALS: Dict[str, Dict[str, float]] = {
    "Acero A36": {"Fy_MPa": 250.0},
    "Acero A572": {"Fy_MPa": 345.0},
    "Aluminio 6061": {"Fy_MPa": 276.0},
}


# -----------------------------
# Core analysis engine
# (Preserves the original logic exactly)
# -----------------------------


class WarrenTruss:
    def __init__(self, L: float, H: float, panels: int, P_total: float):
        self.L = float(L)
        self.H = float(H)
        self.panels = int(panels)
        self.P_total = float(P_total)
        self.results: Dict[str, Any] = {}
        self._analyze()

    def _analyze(self) -> None:
        L, H, n, Pt = self.L, self.H, self.panels, self.P_total
        d = L / n
        diag_len = math.hypot(d, H)
        sin_a = H / diag_len
        angle_deg = math.degrees(math.atan2(H, d))

        load_nodes = n - 1
        P_node = Pt / load_nodes

        Ra = Rb = Pt / 2

        V: List[float] = []
        shear = Ra
        for i in range(n):
            V.append(shear)
            if i < load_nodes:
                shear -= P_node

        bot_forces: List[float] = []
        for i in range(n):
            x_right = (i + 1) * d
            M = Ra * x_right
            if i > 0:
                for j in range(1, i + 1):
                    M -= P_node * (j * d)
            bot_forces.append(M / H)

        top_forces: List[float] = []
        for i in range(n):
            x_mid = (i + 0.5) * d
            M = Ra * x_mid - sum(
                P_node * (j * d) for j in range(1, i + 1) if j * d < x_mid
            )
            top_forces.append(-M / H)

        diag_forces = [V[i] / sin_a for i in range(n)]

        members: List[Dict[str, Any]] = []

        for i, f in enumerate(top_forces):
            members.append(
                {
                    "id": f"CS{i+1}",
                    "name": f"Cordon Superior {i+1}",
                    "type": "top_chord",
                    "force": round(f, 3),
                    "length": round(d, 3),
                    "stress_type": "Compresion" if f < 0 else "Tension",
                }
            )

        for i, f in enumerate(bot_forces):
            members.append(
                {
                    "id": f"CI{i+1}",
                    "name": f"Cordon Inferior {i+1}",
                    "type": "bot_chord",
                    "force": round(f, 3),
                    "length": round(d, 3),
                    "stress_type": "Tension" if f > 0 else "Compresion",
                }
            )

        for i, f in enumerate(diag_forces):
            members.append(
                {
                    "id": f"D{i+1}",
                    "name": f"Diagonal {i+1}",
                    "type": "diagonal",
                    "force": round(f, 3),
                    "length": round(diag_len, 3),
                    "stress_type": "Tension" if f > 0 else "Compresion",
                }
            )

        self.results = {
            "L": L,
            "H": H,
            "panels": n,
            "P_total": Pt,
            "P_node": round(P_node, 3),
            "Ra": round(Ra, 3),
            "Rb": round(Rb, 3),
            "d": round(d, 3),
            "diag": round(diag_len, 3),
            "angle_deg": round(angle_deg, 2),
            "members": members,
            "max_force": round(max(abs(m["force"]) for m in members), 3),
            "n_members": len(members),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def evaluate_safety(self, material: str = "Acero A36", section_area_cm2: float = 50.0) -> Dict[str, Any]:
        Fy_MPa = MATERIALS.get(material, MATERIALS["Acero A36"])["Fy_MPa"]
        allowable_MPa = Fy_MPa / 1.67

        # Convert area
        A_mm2 = section_area_cm2 * 100.0

        member_evals: List[Dict[str, Any]] = []
        critical: List[str] = []
        warnings: List[str] = []

        for m in self.results["members"]:
            F_N = abs(m["force"]) * 1000.0
            sigma_MPa = F_N / A_mm2
            ratio = sigma_MPa / allowable_MPa

            if ratio > 1.0:
                status, color = "FALLA", "danger"
                critical.append(m["id"])
            elif ratio > 0.85:
                status, color = "LIMITE", "warn"
                warnings.append(m["id"])
            else:
                status, color = "SEGURO", "safe"

            member_evals.append(
                {
                    **m,
                    "sigma_MPa": round(sigma_MPa, 2),
                    "allowable_MPa": round(allowable_MPa, 2),
                    "ratio": round(ratio, 3),
                    "status": status,
                    "color": color,
                }
            )

        if critical:
            verdict, v_level = "PELIGROSO", "danger"
        elif warnings:
            verdict, v_level = "PRECAUCION", "warn"
        else:
            verdict, v_level = "SEGURO", "safe"

        sugg = self._suggestions(critical, warnings, member_evals, section_area_cm2, allowable_MPa, material)

        return {
            "verdict": verdict,
            "v_level": v_level,
            "material": material,
            "section_area_cm2": round(section_area_cm2, 1),
            "Fy_MPa": round(Fy_MPa, 0),
            "allowable_MPa": round(allowable_MPa, 1),
            "critical_members": critical,
            "warning_members": warnings,
            "member_evals": member_evals,
            "suggestions": sugg,
        }

    def _suggestions(
        self,
        critical: List[str],
        warnings: List[str],
        evals: List[Dict[str, Any]],
        area_cm2: float,
        allowable_MPa: float,
        material: str,
    ) -> List[str]:
        s: List[str] = []
        hl = self.results["H"] / self.results["L"]

        if critical:
            F_max_N = max(abs(e["force"]) for e in evals) * 1000.0
            A_min_cm2 = (F_max_N / allowable_MPa / 100.0) * 1.15
            s.append(f"Aumentar seccion transversal a minimo {A_min_cm2:.1f} cm2")
            s.append("Considerar material de mayor resistencia (mayor Fy)")

            if self.results["panels"] < 8:
                s.append("Aumentar numero de paneles para reducir fuerzas por miembro")

            if hl < 0.10:
                s.append("Aumentar altura del puente (relacion H/L >= 0.10 recomendada)")

            if material != "Acero A572":
                s.append("Cambiar a Acero A572 (mayor resistencia que A36)")

        elif warnings:
            s.append("Miembros cercanos al limite — revisar cargas de servicio")
            s.append("Aumentar seccion en 15-20% para mayor margen de seguridad")

        else:
            s.append("Diseno dentro de parametros admisibles")
            max_r = max(e["ratio"] for e in evals) if evals else 0
            area_opt = area_cm2 * max_r * 1.10
            if area_opt < area_cm2 * 0.80:
                s.append(f"Podria optimizar la seccion a ~{area_opt:.1f} cm2 (ahorro de material)")

        if hl < 0.08:
            s.append(f"Relacion H/L = {hl:.2f} muy baja — riesgo de pandeo lateral")
        elif hl > 0.20:
            s.append(f"Relacion H/L = {hl:.2f} elevada — revisar cargas de viento")

        return s


# -----------------------------
# History (JSON)
# -----------------------------


class HistoryManager:
    def __init__(self, fp: str = "history.json"):
        self.fp = fp
        self.records = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.fp):
            try:
                with open(self.fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    return []
            except Exception:
                return []
        return []

    def save(self, entry: Dict[str, Any]) -> None:
        self.records.append(entry)
        with open(self.fp, "w", encoding="utf-8") as f:
            json.dump(self.records, f, indent=2, ensure_ascii=False)

    def clear(self) -> None:
        self.records = []
        if os.path.exists(self.fp):
            os.remove(self.fp)

    def get_all(self) -> List[Dict[str, Any]]:
        return list(reversed(self.records))
