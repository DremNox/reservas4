# app/meta.py
import re, time, logging
from urllib.parse import urlparse, parse_qs, unquote
from typing import Optional, Tuple
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait as W
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from .ptp import create_driver
from .utils.ptp_cookies import get_current_cookies, prime_cookies
from .db import execute, fetch_one

logger = logging.getLogger("meta")

RX_KW = re.compile(r"(\d+(?:[.,]\d+)?)\s*kW", re.I)
RX_EUR_KWH = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:€|eur)\s*/\s*kwh", re.I)

def _txt(el) -> str:
    try:
        return (el.text or "").strip()
    except Exception:
        return ""

def _norm_float(s: str) -> Optional[float]:
    if not s: return None
    s = s.replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None

def _first(driver, by, sel):
    els = driver.find_elements(by, sel)
    for e in els:
        t = _txt(e)
        if t: return e, t
    return None, ""

def scrape_punto_info(account_id: int, punto_id: int, url_punto: str):
    """Extrae ficha general del punto y actualiza dbo.PuntoInfo + recuento tomas."""
    t0 = time.time()
    drv = create_driver()
    try:
        cookies = get_current_cookies(account_id)
        prime_cookies(drv, cookies)

        drv.get(url_punto)
        try:
            W(drv, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "app-charging-stations, lib-plug-card")))
        except TimeoutException:
            logger.warning("meta.punto.timeout punto_id=%s url=%s", punto_id, url_punto)

        # Nombre
        _, nombre = (_first(drv, By.CSS_SELECTOR, "h1") or (None,""))
        if not nombre:
            _, nombre = (_first(drv, By.CSS_SELECTOR, "h2, .title, .station-name") or (None,""))

        # Dirección
        _, direccion = (_first(drv, By.CSS_SELECTOR, "[class*='address'], .address, .location") or (None,""))

        # Coordenadas por enlace a maps
        lat = lng = None
        a, _ = _first(drv, By.CSS_SELECTOR, "a[href*='maps'], a[href*='google.com/maps']")
        if a:
            href = a.get_attribute("href") or ""
            try:
                q = parse_qs(urlparse(href).query)
                # buscar "q=lat,lng" ó "!3dLAT!4dLNG"
                if "q" in q:
                    coords = unquote(q["q"][0])
                    if "," in coords:
                        lat, lng = coords.split(",", 1)
                        lat, lng = _norm_float(lat), _norm_float(lng)
            except Exception:
                pass

        # Proveedor (si hay etiqueta)
        prov = ""
        try:
            el = drv.find_element(By.XPATH, "//*[contains(translate(.,'OPERATORPROVEEDOR','operatorproveedor'),'operador') or contains(translate(.,'PROVEEDOR','proveedor'),'proveedor')]/following::*[1]")
            prov = _txt(el)
        except Exception:
            pass

        # Nº tomas visibles
        num_tomas = len(drv.find_elements(By.CSS_SELECTOR, "lib-plug-card"))

        # UPSERT
        execute("""
            MERGE dbo.PuntoInfo AS T
            USING (SELECT :pid AS PuntoId) AS S
            ON (T.PuntoId = S.PuntoId)
            WHEN MATCHED THEN UPDATE SET NombrePTP=:n, Direccion=:d, Lat=:lat, Lng=:lng,
                 Proveedor=:p, ActualizadoUtc=SYSUTCDATETIME()
            WHEN NOT MATCHED THEN
                 INSERT (PuntoId, NombrePTP, Direccion, Lat, Lng, Proveedor)
                 VALUES (:pid, :n, :d, :lat, :lng, :p);
        """, pid=punto_id, n=nombre or None, d=direccion or None, lat=lat, lng=lng, p=prov or None)

        logger.info("meta.punto.ok punto_id=%s nombre=%s tomas=%s dur_ms=%s",
                    punto_id, nombre or "-", num_tomas, int((time.time()-t0)*1000))
        return {"nombre": nombre, "direccion": direccion, "lat": lat, "lng": lng, "proveedor": prov, "num_tomas": num_tomas}

    finally:
        try: drv.quit()
        except Exception: pass

def scrape_conector_info(account_id: int, conector_id: int, url_conector: str):
    """Extrae ficha del conector y upsert en dbo.ConectorInfo."""
    t0 = time.time()
    drv = create_driver()
    try:
        cookies = get_current_cookies(account_id)
        prime_cookies(drv, cookies)

        drv.get(url_conector)
        try:
            W(drv, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "lib-plug-card, lib-status-indicator")))
        except TimeoutException:
            logger.warning("meta.conector.timeout conector_id=%s url=%s", conector_id, url_conector)

        # Tipo
        _, tipo = (_first(drv, By.CSS_SELECTOR, "lib-plug-card .plug-name, .connector, .type, [class*='tipo']") or (None,""))

        # Potencia (buscamos en todo el DOM, normalizamos)
        potencia_kw = None
        for el in drv.find_elements(By.XPATH, "//*[contains(.,'kW') and not(self::script) and not(self::style)]"):
            m = RX_KW.search(_txt(el))
            if m:
                potencia_kw = _norm_float(m.group(1))
                if potencia_kw: break

        # Precio
        precio_texto = ""
        for el in drv.find_elements(By.CSS_SELECTOR, ".price, .tariff, .pricing, lib-price, [class*='precio']"):
            t = _txt(el)
            if t:
                precio_texto = t
                break
        if not precio_texto:
            # fallback texto global
            for el in drv.find_elements(By.XPATH, "//*[contains(translate(.,'€EURKWH','€eurkwh'),'€') or contains(.,'/kWh')]"):
                t = _txt(el)
                if t:
                    precio_texto = t
                    break

        precio_kwh = None
        modelo = None
        if precio_texto:
            m = RX_EUR_KWH.search(precio_texto.replace(",", "."))
            if m:
                precio_kwh = _norm_float(m.group(1))
                modelo = "kWh"
            elif "sesión" in precio_texto.lower():
                modelo = "sesion"
            elif "/min" in precio_texto.lower() or "minuto" in precio_texto.lower():
                modelo = "minuto"

        execute("""
            MERGE dbo.ConectorInfo AS T
            USING (SELECT :cid AS ConectorId) AS S
            ON (T.ConectorId = S.ConectorId)
            WHEN MATCHED THEN UPDATE SET
                Tipo=:tipo, PotenciaKw=:pkw, PrecioTexto=:pt, PrecioKwh=:pkwh, TarifaModelo=:tm, ActualizadoUtc=SYSUTCDATETIME()
            WHEN NOT MATCHED THEN
                INSERT (ConectorId, Tipo, PotenciaKw, PrecioTexto, PrecioKwh, TarifaModelo)
                VALUES (:cid, :tipo, :pkw, :pt, :pkwh, :tm);
        """, cid=conector_id, tipo=tipo or None, pkw=potencia_kw, pt=precio_texto or None, pkwh=precio_kwh, tm=modelo or None)

        logger.info("meta.conector.ok conector_id=%s tipo=%s kW=%s precio=%s dur_ms=%s",
                    conector_id, tipo or "-", potencia_kw, precio_texto or "-", int((time.time()-t0)*1000))
        return {"tipo": tipo, "potencia_kw": potencia_kw, "precio_texto": precio_texto, "precio_kwh": precio_kwh, "modelo": modelo}

    finally:
        try: drv.quit()
        except Exception: pass
