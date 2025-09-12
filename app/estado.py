# app/estado.py
import time, logging
from typing import Optional, Tuple
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait as W
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from .ptp import create_driver
from .utils.ptp_cookies import get_current_cookies, prime_cookies
from .db import execute

logger = logging.getLogger("estado")

STATUS_CLASS_MAP = {
    "light-green-pulse": "Libre", "s-light-green": "Libre", "s-success": "Libre",
    "light-blue-pulse": "Ocupado", "s-light-blue": "Ocupado", "danger": "Ocupado",
    "s-orange": "Reservado", "orange": "Reservado", "warning": "Reservado",
    "s-grey": "No disponible", "s-gray": "No disponible", "grey": "No disponible", "gray": "No disponible",
    "error": "Averiado", "fault": "Averiado"
}
STATUS_TEXT_MAP = {
    "libre": "Libre",
    "ocupado": "Ocupado",
    "reservado": "Reservado",
    "no disponible": "No disponible",
    "averiado": "Averiado",
    "fuera de servicio": "Averiado",
}

def _infer_status_by_class(driver) -> Optional[Tuple[str,str]]:
    # Busca cualquier badge/estado por clases
    for cls, label in STATUS_CLASS_MAP.items():
        els = driver.find_elements(By.XPATH, f"//*[contains(@class,'{cls}')]")
        if els:
            return label, f"class:{cls}"
    return None

def _infer_status_by_text(driver) -> Optional[Tuple[str,str]]:
    texts = [e.text.strip().lower() for e in driver.find_elements(By.XPATH, "//*[normalize-space(text())!='']")]
    joined = " | ".join(texts)
    for key, label in STATUS_TEXT_MAP.items():
        if key in joined:
            return label, f"text:{key}"
    return None

def extract_status(driver) -> Tuple[str, str]:
    """Devuelve (estado, raw_hint). Si no detecta, 'Desconocido'."""
    hit = _infer_status_by_class(driver) or _infer_status_by_text(driver)
    if hit:
        return hit[0], hit[1]
    return "Desconocido", "none"

def scrape_conector_estado(account_id: int, conector_id: int, url_conector: str) -> Tuple[str, str]:
    """Navega con cookies a la URL del conector y guarda estado en BD."""
    t0 = time.time()
    drv = create_driver()
    try:
        cookies = get_current_cookies(account_id)
        prime_cookies(drv, cookies)

        drv.get(url_conector)
        # espera razonable a que cargue contenido
        try:
            W(drv, 12).until(EC.presence_of_element_located((By.XPATH, "//*")))
        except TimeoutException:
            pass

        estado, hint = extract_status(drv)
        logger.info("estado.conector conector_id=%s estado=%s hint=%s duration_ms=%s",
                    conector_id, estado, hint, int((time.time()-t0)*1000))

        execute("""
          INSERT INTO dbo.EstadosConector (ConectorId, Estado, Precio, RawHint)
          VALUES (:cid, :est, NULL, :hint)
        """, cid=conector_id, est=estado, hint=hint)

        return estado, hint
    finally:
        try: drv.quit()
        except Exception: pass
