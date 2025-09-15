# app/meta.py
import re, time, logging
from urllib.parse import urlparse, parse_qs, unquote
from typing import Optional, Tuple
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait as W
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from .ptp import create_driver
from .utils.ptp_cookies import get_current_cookies, prime_cookies
from .db import execute

logger = logging.getLogger("meta")

# --- helpers ---------------------------------------------------

RX_KW       = re.compile(r"(\d+(?:[.,]\d+)?)\s*kW", re.I)
RX_EUR_KWH  = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:€|EUR)\s*/\s*kWh", re.I)

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

def first_text(driver, xpath: str | None = None, css: str | None = None) -> str:
    # Prioriza XPath → CSS
    if xpath:
        els = driver.find_elements(By.XPATH, xpath)
        for e in els:
            t = _txt(e)
            if t: return t
    if css:
        els = driver.find_elements(By.CSS_SELECTOR, css)
        for e in els:
            t = _txt(e)
            if t: return t
    return ""

def wait_dom(driver, sec=15):
    try:
        W(driver, sec).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "app-charging-stations, lib-plug-card, lib-status-indicator, .zone-title")
        ))
    except TimeoutException:
        pass

# --- manifiesto con tus selectores ----------------------------

MANIF_PUNTO = {
    "nombre": {
        "xpath": r"//h1[@class='zone-title']",
        "css":  r".zone-title",
    },
    "direccion": {
        "xpath": r"//label[normalize-space()='CALLE BORRIOL, Sant Joan de Moró']",
        "css":  r"div.header-info-texts label",
    },
    "proveedor": {
        "xpath": r"//label[@class='title-centered']",
        "css":  r".title-centered",
    },
    "latlng": {
        # buscamos el bloque "Cómo llegar", y de ahí subimos a <a> para leer el href con "destination=lat,lng"
        "xpath": r"//div[normalize-space()='Cómo llegar']",
        "css":  r"div.header-actions div:nth-child(3)",
        "param": "destination",  # destination=lat,lng
    },
    "num_tomas": {
        "xpath": r"//*[@id='6465fa1c60ec9387ca9ca26d']/div[1]/lib-service-plugs[1]/div[2]/lib-plug-card/div[2]/div[2]",
        "css":  r"body > app-root:nth-child(2) > div:nth-child(4) > app-route-wrapper:nth-child(2) > app-application:nth-child(1) > div:nth-child(2) > div:nth-child(1) > app-charging-stations:nth-child(2) > div:nth-child(1) > div:nth-child(4) > lib-zone-detail:nth-child(1) > div:nth-child(1) > div:nth-child(3) > div:nth-child(1) > cdk-virtual-scroll-viewport:nth-child(1) > div:nth-child(1) > div:nth-child(2) > div:nth-child(2) > div:nth-child(2) > div:nth-child(2) > cdk-virtual-scroll-viewport:nth-child(1) > div:nth-child(1) > lib-service-plugs:nth-child(1) > div:nth-child(3) > lib-plug-card:nth-child(1) > div:nth-child(2) > div:nth-child(2)",
        "fallback_css": "lib-plug-card"
    },
    "potencia_max_kw": {
        "xpath": "",
        "css":  "",
        "regex": RX_KW,
    },
}

MANIF_CONECTOR = {
    "tipo": {
        "xpath": r"//div[@class='plug-name']",
        "css":  r".plug-name",
    },
    "potencia_kw": {
        "xpath": r"//div[@class='power']",
        "css":  r".power",
        "regex": RX_KW,
    },
    "precio_texto": {
        "xpath": r"/html/body/app-root/div/app-route-wrapper/app-application/div[2]/div/app-charging-stations/div/div[2]/div/lib-start-action/div[1]/div[1]/lib-plug-card/div[2]/button",
        "css":  r".price, .tariff, .pricing, lib-price, lib-plug-card button.button-primary",
    },
    "precio_kwh": {
        "regex": RX_EUR_KWH
    }
}

# --- scraping punto -------------------------------------------

def _latlng_from_destination(href: str, param="destination") -> Tuple[Optional[float], Optional[float]]:
    try:
        if not href: return None, None
        q = parse_qs(urlparse(href).query)
        if param in q:
            coords = unquote(q[param][0])
            if "," in coords:
                lat, lng = coords.split(",", 1)
                return _norm_float(lat), _norm_float(lng)
    except Exception:
        pass
    return None, None

def scrape_punto_info(account_id: int, punto_id: int, url_punto: str):
    t0 = time.time()
    drv = create_driver()
    try:
        cookies = get_current_cookies(account_id)
        prime_cookies(drv, cookies)
        drv.get(url_punto)
        wait_dom(drv, 15)

        # Nombre / Dirección / Proveedor
        nombre    = first_text(drv, MANIF_PUNTO["nombre"]["xpath"],    MANIF_PUNTO["nombre"]["css"])
        direccion = first_text(drv, MANIF_PUNTO["direccion"]["xpath"], MANIF_PUNTO["direccion"]["css"])
        proveedor = first_text(drv, MANIF_PUNTO["proveedor"]["xpath"], MANIF_PUNTO["proveedor"]["css"])

        # Lat/Lng desde "Cómo llegar" → <a href="...destination=lat,lng...">
        lat = lng = None
        # 1) intenta encontrar el div, subir a <a> cercano
        lat_sel = MANIF_PUNTO["latlng"]
        lat_anchor = None
        try:
            node = None
            if lat_sel["xpath"]:
                els = drv.find_elements(By.XPATH, lat_sel["xpath"])
                node = els[0] if els else None
            if not node and lat_sel["css"]:
                els = drv.find_elements(By.CSS_SELECTOR, lat_sel["css"])
                node = els[0] if els else None
            cur = node
            steps = 0
            while cur is not None and steps < 5:
                # ¿es un <a>?
                try:
                    tag = (cur.tag_name or "").lower()
                except Exception:
                    tag = ""
                if tag == "a":
                    lat_anchor = cur
                    break
                try:
                    cur = cur.find_element(By.XPATH, "./..")
                except Exception:
                    break
                steps += 1
        except Exception:
            pass
        if not lat_anchor:
            # 2) fallback: cualquier <a> con destination=
            anchors = drv.find_elements(By.CSS_SELECTOR, "a[href*='destination=']")
            lat_anchor = anchors[0] if anchors else None
        if lat_anchor:
            href = lat_anchor.get_attribute("href") or ""
            lat, lng = _latlng_from_destination(href, lat_sel.get("param","destination"))

        # Nº tomas
        num_xpath = MANIF_PUNTO["num_tomas"]["xpath"]
        num_css   = MANIF_PUNTO["num_tomas"]["css"]
        fb_css    = MANIF_PUNTO["num_tomas"]["fallback_css"]
        num_tomas = 0
        try:
            els = drv.find_elements(By.XPATH, num_xpath) if num_xpath else []
            num_tomas = len(els)
            if num_tomas == 0 and num_css:
                els = drv.find_elements(By.CSS_SELECTOR, num_css)
                num_tomas = len(els)
            if num_tomas == 0 and fb_css:
                els = drv.find_elements(By.CSS_SELECTOR, fb_css)
                num_tomas = len(els)
        except Exception:
            pass

        # Potencia máx. (si existiera a nivel punto)
        pmax_kw = None
        if MANIF_PUNTO["potencia_max_kw"]["xpath"] or MANIF_PUNTO["potencia_max_kw"]["css"]:
            raw = first_text(drv, MANIF_PUNTO["potencia_max_kw"]["xpath"], MANIF_PUNTO["potencia_max_kw"]["css"])
            if raw:
                m = MANIF_PUNTO["potencia_max_kw"]["regex"].search(raw)
                if m:
                    pmax_kw = _norm_float(m.group(1))

        # UPSERT en dbo.PuntoInfo
        execute("""
            MERGE dbo.PuntoInfo AS T
            USING (SELECT :pid AS PuntoId) AS S
            ON (T.PuntoId = S.PuntoId)
            WHEN MATCHED THEN UPDATE SET
                NombrePTP=:n, Direccion=:d, Lat=:lat, Lng=:lng, Proveedor=:pr, ActualizadoUtc=SYSUTCDATETIME()
            WHEN NOT MATCHED THEN
                INSERT (PuntoId, NombrePTP, Direccion, Lat, Lng, Proveedor)
                VALUES (:pid, :n, :d, :lat, :lng, :pr);
        """, pid=punto_id, n=(nombre or None), d=(direccion or None),
             lat=lat, lng=lng, pr=(proveedor or None))

        logger.info("meta.punto.ok punto_id=%s nombre='%s' tomas=%s lat=%s lng=%s dur_ms=%s",
                    punto_id, nombre or "-", num_tomas, lat, lng, int((time.time()-t0)*1000))

        return {"nombre": nombre, "direccion": direccion, "proveedor": proveedor,
                "lat": lat, "lng": lng, "num_tomas": num_tomas, "potencia_max_kw": pmax_kw}

    finally:
        try: drv.quit()
        except Exception: pass

# --- scraping conector ----------------------------------------

def scrape_conector_info(account_id: int, conector_id: int, url_conector: str):
    t0 = time.time()
    drv = create_driver()
    try:
        cookies = get_current_cookies(account_id)
        prime_cookies(drv, cookies)
        drv.get(url_conector)
        wait_dom(drv, 15)

        # Tipo
        tipo = first_text(drv, MANIF_CONECTOR["tipo"]["xpath"], MANIF_CONECTOR["tipo"]["css"])

        # Potencia (texto → regex)
        raw_p = first_text(drv, MANIF_CONECTOR["potencia_kw"]["xpath"], MANIF_CONECTOR["potencia_kw"]["css"])
        potencia_kw = None
        if raw_p:
            m = MANIF_CONECTOR["potencia_kw"]["regex"].search(raw_p)
            if m:
                potencia_kw = _norm_float(m.group(1))
        if potencia_kw is None:
            # fallback: buscar en todo el DOM
            for el in drv.find_elements(By.XPATH, "//*[contains(.,'kW') and not(self::script) and not(self::style)]"):
                m = RX_KW.search(_txt(el))
                if m:
                    potencia_kw = _norm_float(m.group(1)); break

        # Precio texto
        precio_texto = first_text(drv, MANIF_CONECTOR["precio_texto"]["xpath"], MANIF_CONECTOR["precio_texto"]["css"])
        precio_kwh = None
        modelo = None
        if precio_texto:
            low = precio_texto.lower()
            if "gratis" in low:
                precio_kwh = 0.0
                modelo = "gratis"
            else:
                m = MANIF_CONECTOR["precio_kwh"]["regex"].search(precio_texto.replace(",", "."))
                if m:
                    precio_kwh = _norm_float(m.group(1))
                    modelo = "kWh"
                elif "sesión" in low:
                    modelo = "sesion"
                elif "/min" in low or "minuto" in low:
                    modelo = "minuto"

        # UPSERT en dbo.ConectorInfo
        execute("""
            MERGE dbo.ConectorInfo AS T
            USING (SELECT :cid AS ConectorId) AS S
            ON (T.ConectorId = S.ConectorId)
            WHEN MATCHED THEN UPDATE SET
                Tipo=:tipo, PotenciaKw=:pkw, PrecioTexto=:pt, PrecioKwh=:pkwh, TarifaModelo=:tm, ActualizadoUtc=SYSUTCDATETIME()
            WHEN NOT MATCHED THEN
                INSERT (ConectorId, Tipo, PotenciaKw, PrecioTexto, PrecioKwh, TarifaModelo)
                VALUES (:cid, :tipo, :pkw, :pt, :pkwh, :tm);
        """, cid=conector_id, tipo=(tipo or None), pkw=potencia_kw,
             pt=(precio_texto or None), pkwh=precio_kwh, tm=(modelo or None))

        logger.info("meta.conector.ok conector_id=%s tipo='%s' kW=%s precio='%s' modelo=%s dur_ms=%s",
                    conector_id, tipo or "-", potencia_kw, precio_texto or "-", modelo,
                    int((time.time()-t0)*1000))

        return {"tipo": tipo, "potencia_kw": potencia_kw, "precio_texto": precio_texto,
                "precio_kwh": precio_kwh, "modelo": modelo}

    finally:
        try: drv.quit()
        except Exception: pass
