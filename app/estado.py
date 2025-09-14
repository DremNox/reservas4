# app/estado.py
import time, logging
from typing import Optional, Tuple
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait as W
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from .ptp import create_driver, LOGS_DIR
from .utils.ptp_cookies import get_current_cookies, prime_cookies
from .db import execute

logger = logging.getLogger("estado")

# ✅ Mapeos ampliados (incluye s-light-*)
STATUS_CLASS_MAP = {
    # “oscuros”
    "s-green": "Libre", "green": "Libre", "s-success": "Libre",
    "s-red": "Ocupado", "red": "Ocupado", "danger": "Ocupado",
    "s-orange": "Reservado", "orange": "Reservado", "warning": "Reservado",
    "s-grey": "No disponible", "s-gray": "No disponible", "grey": "No disponible", "gray": "No disponible",
    "error": "Averiado", "fault": "Averiado",

    # “claros” (tu caso)
    "s-light-green": "Libre",
    "s-light-orange": "Reservado",
    "s-light-red": "Ocupado",
    "s-light-grey": "No disponible",
    "s-light-gray": "No disponible",
}

STATUS_TEXT_MAP = {
    "libre": "Libre",
    "ocupado": "Ocupado",
    "reservado": "Reservado",
    "no disponible": "No disponible",
    "averiado": "Averiado",
    "fuera de servicio": "Averiado",
}

def _infer_from_status_indicator(driver) -> Optional[Tuple[str, str]]:
    """
    Busca <lib-status-indicator ... class="s-light-green"> dentro de la zona de estado.
    """
    # CSS directo (tu JSXpath): div.status lib-status-indicator[class*='s-']
    try:
        els = driver.find_elements(By.CSS_SELECTOR, "div.status lib-status-indicator")
        if not els:
            # fallback más amplio
            els = driver.find_elements(By.CSS_SELECTOR, "lib-status-indicator")
        for el in els:
            cls = (el.get_attribute("class") or "").strip()
            if not cls:
                continue
            classes = [c.strip() for c in cls.split() if c.strip()]
            for c in classes:
                if c in STATUS_CLASS_MAP:
                    return STATUS_CLASS_MAP[c], f"indicator:{c}"
    except Exception:
        pass
    return None

def _infer_status_by_class_anywhere(driver) -> Optional[Tuple[str,str]]:
    for cls, label in STATUS_CLASS_MAP.items():
        els = driver.find_elements(By.XPATH, f"//*[contains(@class,'{cls}')]")
        if els:
            return label, f"class:{cls}"
    return None

def _infer_status_by_text(driver) -> Optional[Tuple[str,str]]:
    try:
        texts = [e.text.strip().lower() for e in driver.find_elements(By.XPATH, "//*[normalize-space(text())!='']")]
        joined = " | ".join(texts)
        for key, label in STATUS_TEXT_MAP.items():
            if key in joined:
                return label, f"text:{key}"
    except Exception:
        pass
    return None

def extract_status(driver) -> Tuple[str, str]:
    """
    Devuelve (estado, raw_hint). Orden de preferencia:
    - lib-status-indicator (clases s-light-*)
    - cualquier clase conocida en el DOM
    - heurística por texto
    """
    hit = (
        _infer_from_status_indicator(driver)
        or _infer_status_by_class_anywhere(driver)
        or _infer_status_by_text(driver)
    )
    if hit:
        return hit[0], hit[1]
    return "Desconocido", "none"

def scrape_conector_estado(account_id: int, conector_id: int, url_conector: str) -> Tuple[str, str]:
    t0 = time.time()
    drv = create_driver()
    try:
        cookies = get_current_cookies(account_id)
        prime_cookies(drv, cookies)

        drv.get(url_conector)

        # ✅ Espera a que Angular pueble la vista de puntos
        try:
            W(drv, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "app-charging-stations, lib-plug-card, lib-status-indicator")))
        except TimeoutException:
            logger.warning("estado.timeout.root conector_id=%s url=%s", conector_id, url_conector)

        estado, hint = extract_status(drv)
        logger.info("estado.conector conector_id=%s estado=%s hint=%s duration_ms=%s",
                    conector_id, estado, hint, int((time.time()-t0)*1000))

        execute("""
          INSERT INTO dbo.EstadosConector (ConectorId, Estado, Precio, RawHint)
          VALUES (:cid, :est, NULL, :hint)
        """, cid=conector_id, est=estado, hint=hint)

        # Si no encontramos nada, deja captura para depurar selectores reales
        if estado == "Desconocido":
            try:
                shot = LOGS_DIR / f"estado_unknown_{conector_id}_{int(time.time())}.png"
                drv.save_screenshot(str(shot))
                logger.warning("estado.desconocido screenshot=%s", shot)
            except Exception:
                pass

        return estado, hint
    finally:
        try: drv.quit()
        except Exception: pass
