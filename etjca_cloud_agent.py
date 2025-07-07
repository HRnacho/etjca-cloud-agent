# etjca_cloud_agent.py
# Copiare il contenuto dall'artifact corrispondente
#!/usr/bin/env python3
"""
ETJCA Lead Generation Agent - Cloud Version
Hosting: Railway/Render/Heroku
Database: PostgreSQL
Features: Web Scraping, Email, LinkedIn, Reports
"""

import os
import json
import psycopg2
import requests
import smtplib
import schedule
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
import logging
from bs4 import BeautifulSoup
import pandas as pd
from flask import Flask, render_template_string, jsonify, request, send_file
import threading
from urllib.parse import urljoin, urlparse
import re
import ssl
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
import io
import zipfile

# Configurazione logging cloud
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # Solo console per cloud
    ]
)

@dataclass
class Prospect:
    """Modello Prospect per database"""
    ragione_sociale: str
    settore: str
    fatturato: Optional[float]
    dipendenti: Optional[int]
    indirizzo: str
    provincia: str
    telefono: Optional[str]
    email: Optional[str]
    sito_web: Optional[str]
    nome_hr: Optional[str]
    cognome_hr: Optional[str]
    email_hr: Optional[str]
    linkedin_hr: Optional[str]
    linkedin_company: Optional[str]
    fonte: str
    data_inserimento: datetime
    stato: str = "nuovo"
    priorita: str = "media"
    note: str = ""
    codice_ateco: Optional[str] = None
    piva: Optional[str] = None
    codice_fiscale: Optional[str] = None

@dataclass
class Attivita:
    """Modello Attività"""
    id_prospect: int
    tipo: str  # email, chiamata, meeting, linkedin, note
    data: datetime
    oggetto: str
    descrizione: str
    esito: str
    prossima_azione: Optional[str]
    data_prossima_azione: Optional[datetime]
    allegati: Optional[str] = None

class CloudDatabaseManager:
    """Gestione database PostgreSQL cloud"""
    
    def __init__(self):
        # Variabili ambiente per database cloud
        self.db_url = os.getenv('DATABASE_URL')
        if not self.db_url:
            # Fallback per sviluppo locale
            self.db_url = "postgresql://localhost/etjca_db"
        
        self.init_database()
    
    def get_connection(self):
        """Connessione sicura al database"""
        return psycopg2.connect(self.db_url, sslmode='require')
    
    def init_database(self):
        """Inizializza schema database PostgreSQL"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Tabella prospect con campi estesi
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS prospect (
                id SERIAL PRIMARY KEY,
                ragione_sociale VARCHAR(255) NOT NULL,
                settore VARCHAR(100),
                fatturato BIGINT,
                dipendenti INTEGER,
                indirizzo TEXT,
                provincia VARCHAR(50),
                telefono VARCHAR(50),
                email VARCHAR(255),
                sito_web VARCHAR(255),
                nome_hr VARCHAR(100),
                cognome_hr VARCHAR(100),
                email_hr VARCHAR(255),
                linkedin_hr VARCHAR(255),
                linkedin_company VARCHAR(255),
                fonte VARCHAR(50),
                data_inserimento TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                stato VARCHAR(50) DEFAULT 'nuovo',
                priorita VARCHAR(20) DEFAULT 'media',
                note TEXT,
                codice_ateco VARCHAR(20),
                piva VARCHAR(20),
                codice_fiscale VARCHAR(20),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabella attività
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attivita (
                id SERIAL PRIMARY KEY,
                id_prospect INTEGER REFERENCES prospect(id),
                tipo VARCHAR(50),
                data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                oggetto VARCHAR(255),
                descrizione TEXT,
                esito VARCHAR(100),
                prossima_azione VARCHAR(255),
                data_prossima_azione TIMESTAMP,
                allegati TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabella configurazioni
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS configurazioni (
                id SERIAL PRIMARY KEY,
                chiave VARCHAR(100) UNIQUE,
                valore TEXT,
                descrizione TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabella email_templates
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS email_templates (
                id SERIAL PRIMARY KEY,
                nome VARCHAR(100),
                oggetto VARCHAR(255),
                corpo TEXT,
                tipo VARCHAR(50),
                attivo BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Tabella log_sistema
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS log_sistema (
                id SERIAL PRIMARY KEY,
                livello VARCHAR(20),
                messaggio TEXT,
                modulo VARCHAR(100),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Indici per performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_prospect_stato ON prospect(stato)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_prospect_fonte ON prospect(fonte)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_prospect_provincia ON prospect(provincia)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_attivita_data ON attivita(data)')
        
        conn.commit()
        conn.close()
        
        # Inserisci configurazioni di default
        self.setup_default_config()
        self.setup_email_templates()
        
        logging.info("✅ Database PostgreSQL inizializzato")
    
    def setup_default_config(self):
        """Setup configurazioni di default"""
        default_configs = [
            ('nome_account', 'Account Manager ETJCA', 'Nome dell\'account manager'),
            ('email_account', 'account@etjca.it', 'Email dell\'account manager'),
            ('telefono_account', '+39 XXX XXXXXXX', 'Telefono account manager'),
            ('smtp_server', 'smtp.gmail.com', 'Server SMTP per email'),
            ('smtp_port', '587', 'Porta SMTP'),
            ('max_email_giorno', '50', 'Limite email giornaliere'),
            ('max_ricerche_linkedin', '20', 'Limite ricerche LinkedIn giornaliere'),
            ('provincie_target', 'Udine,Pordenone,Gorizia,Trieste', 'Province target FVG'),
            ('settori_target', 'Manifatturiero,Metalmeccanico,Edilizia,Logistica', 'Settori target'),
            ('fatturato_minimo', '2000000', 'Fatturato minimo prospect'),
            ('dipendenti_minimi', '50', 'Dipendenti minimi prospect'),
            ('orario_esecuzione', '08:00', 'Orario esecuzione giornaliera'),
            ('giorni_follow_up', '3,7,14', 'Giorni per follow-up automatici'),
            ('webhook_teams', '', 'Webhook Microsoft Teams per notifiche'),
            ('api_key_maps', '', 'API Key Google Maps per geolocalizzazione'),
            ('proxy_list', '', 'Lista proxy per web scraping')
        ]
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for chiave, valore, descrizione in default_configs:
            cursor.execute('''
                INSERT INTO configurazioni (chiave, valore, descrizione)
                VALUES (%s, %s, %s)
                ON CONFLICT (chiave) DO NOTHING
            ''', (chiave, valore, descrizione))
        
        conn.commit()
        conn.close()
    
    def setup_email_templates(self):
        """Setup template email ETJCA"""
        templates = [
            {
                'nome': 'prima_email',
                'oggetto': 'ETJCA - Partnership per {ragione_sociale}',
                'corpo': '''Gentile {nome_hr} {cognome_hr},

Mi presento, sono {nome_account} di ETJCA, una delle prime dieci agenzie per il lavoro in Italia con oltre 25 anni di esperienza nel settore delle risorse umane.

Ho notato che {ragione_sociale} opera con successo nel settore {settore} in Friuli Venezia Giulia, e credo che possiamo offrire un valore significativo alla vostra crescita aziendale.

ETJCA offre soluzioni complete per la gestione delle risorse umane:
• Somministrazione di lavoro a tempo determinato e indeterminato
• Ricerca e selezione del personale specializzato
• Formazione professionale e sviluppo competenze
• Outsourcing HR e gestione amministrativa
• Politiche attive del lavoro e incentivi

La nostra esperienza nel territorio friulano ci permette di comprendere le specifiche esigenze del mercato locale e di fornire candidati qualificati in tempi rapidi.

Sarei lieto di illustrarle personalmente come ETJCA può supportare i vostri obiettivi di crescita.

Sarebbe disponibile per un breve incontro, anche via Microsoft Teams, nella prossima settimana?

Resto a disposizione per qualsiasi informazione.

Cordiali saluti,

{nome_account}
Account Manager ETJCA Friuli Venezia Giulia
📞 {telefono}
✉️ {email}
🌐 www.etjca.it

P.S. Allegato trova la nostra brochure con i servizi dedicati alle aziende del territorio.''',
                'tipo': 'primo_contatto'
            },
            {
                'nome': 'follow_up_1',
                'oggetto': 'ETJCA - Seguimento proposta per {ragione_sociale}',
                'corpo': '''Gentile {nome_hr} {cognome_hr},

Spero che la mia precedente email sia arrivata a destinazione.

Comprendo che sia un periodo impegnativo, ma volevo sottolineare come ETJCA possa essere un partner strategico per {ragione_sociale} in questo momento di crescita del mercato del lavoro.

In particolare, per aziende come la vostra nel settore {settore}, stiamo supportando diversi clienti con:
• Copertura di posizioni critiche in tempi ridotti
• Gestione dei picchi stagionali di produzione
• Selezione di profili specializzati difficili da trovare
• Formazione finanziata per lo sviluppo interno

Sarebbe possibile concordare una breve call di 15 minuti per valutare insieme come possiamo esservi utili?

Resto a disposizione per organizzare l'incontro nel giorno e orario a voi più comodo.

Cordiali saluti,

{nome_account}
Account Manager ETJCA FVG''',
                'tipo': 'follow_up'
            },
            {
                'nome': 'conferma_appuntamento',
                'oggetto': 'ETJCA - Conferma appuntamento {data_appuntamento}',
                'corpo': '''Gentile {nome_hr} {cognome_hr},

La ringrazio per la disponibilità mostrata.

Come concordato, confermo l'appuntamento per {data_appuntamento} alle {ora_appuntamento}.

Per l'incontro via Microsoft Teams, utilizzeremo il seguente link:
{link_teams}

Durante l'incontro avremo modo di:
• Analizzare le vostre esigenze specifiche nel settore {settore}
• Presentare le nostre soluzioni personalizzate
• Discutere case study di successo con aziende simili in FVG
• Valutare opportunità di collaborazione immediate

Allego la presentazione che utilizzeremo come base per la discussione.

Non esiti a contattarmi per qualsiasi necessità.

Cordiali saluti,

{nome_account}
Account Manager ETJCA FVG''',
                'tipo': 'appuntamento'
            }
        ]
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        for template in templates:
            cursor.execute('''
                INSERT INTO email_templates (nome, oggetto, corpo, tipo)
                VALUES (%(nome)s, %(oggetto)s, %(corpo)s, %(tipo)s)
                ON CONFLICT DO NOTHING
            ''', template)
        
        conn.commit()
        conn.close()
    
    def insert_prospect(self, prospect: Prospect) -> int:
        """Inserisce prospect nel database"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO prospect (
                ragione_sociale, settore, fatturato, dipendenti, indirizzo, provincia,
                telefono, email, sito_web, nome_hr, cognome_hr, email_hr,
                linkedin_hr, linkedin_company, fonte, stato, priorita, note,
                codice_ateco, piva, codice_fiscale
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            prospect.ragione_sociale, prospect.settore, prospect.fatturato,
            prospect.dipendenti, prospect.indirizzo, prospect.provincia,
            prospect.telefono, prospect.email, prospect.sito_web,
            prospect.nome_hr, prospect.cognome_hr, prospect.email_hr,
            prospect.linkedin_hr, prospect.linkedin_company, prospect.fonte,
            prospect.stato, prospect.priorita, prospect.note,
            prospect.codice_ateco, prospect.piva, prospect.codice_fiscale
        ))
        
        prospect_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        
        self.log_sistema('INFO', f'Prospect inserito: {prospect.ragione_sociale}', 'DatabaseManager')
        return prospect_id
    
    def insert_attivita(self, attivita: Attivita):
        """Inserisce attività nel database"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO attivita (
                id_prospect, tipo, oggetto, descrizione, esito,
                prossima_azione, data_prossima_azione, allegati
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            attivita.id_prospect, attivita.tipo, attivita.oggetto,
            attivita.descrizione, attivita.esito, attivita.prossima_azione,
            attivita.data_prossima_azione, attivita.allegati
        ))
        
        conn.commit()
        conn.close()
        
        self.log_sistema('INFO', f'Attività inserita: {attivita.tipo} per prospect {attivita.id_prospect}', 'DatabaseManager')
    
    def log_sistema(self, livello: str, messaggio: str, modulo: str):
        """Log nel database"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO log_sistema (livello, messaggio, modulo)
                VALUES (%s, %s, %s)
            ''', (livello, messaggio, modulo))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logging.error(f"Errore log database: {e}")
    
    def get_config(self, chiave: str) -> str:
        """Recupera configurazione"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT valore FROM configurazioni WHERE chiave = %s', (chiave,))
        result = cursor.fetchone()
        
        conn.close()
        return result[0] if result else None

class AdvancedWebScraper:
    """Web Scraper avanzato per Camera Commercio e directory"""
    
    def __init__(self, db_manager: CloudDatabaseManager):
        self.db_manager = db_manager
        self.setup_driver()
        
        # API endpoints
        self.endpoints = {
            'camera_commercio_fvg': 'https://www.infocamere.it/ricerca-imprese',
            'pagine_gialle': 'https://www.paginegialle.it/ricerca',
            'europages': 'https://www.europages.it/ricerca-aziende',
            'kompass': 'https://it.kompass.com/searchCompanies',
            'atoka_api': 'https://api.atoka.io/v1/companies'  # API professionale
        }
    
    def setup_driver(self):
        """Setup Selenium per cloud"""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-plugins")
        chrome_options.add_argument("--disable-images")
        chrome_options.add_argument("--disable-javascript")  # Per velocità
        
        # User agent realistico
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            self.wait = WebDriverWait(self.driver, 10)
            logging.info("✅ WebDriver inizializzato per cloud")
        except Exception as e:
            logging.error(f"❌ Errore setup WebDriver: {e}")
            self.driver = None
    
    def search_camera_commercio_fvg(self, settore: str, provincia: str) -> List[Prospect]:
        """Ricerca avanzata Camera di Commercio FVG"""
        prospects = []
        
        if not self.driver:
            logging.warning("WebDriver non disponibile")
            return prospects
        
        try:
            # Parametri di ricerca specifici per FVG
            search_params = {
                'provincia': provincia,
                'settore': settore,
                'fatturato_min': self.db_manager.get_config('fatturato_minimo'),
                'dipendenti_min': self.db_manager.get_config('dipendenti_minimi')
            }
            
            logging.info(f"🔍 Ricerca Camera Commercio: {settore} in {provincia}")
            
            # Simula ricerca (implementazione specifica per API Camera Commercio)
            self.driver.get("https://www.registroimprese.it/")
            time.sleep(2)
            
            # Inserisci criteri di ricerca
            # (Implementazione dettagliata basata su DOM specifico)
            
            # Per ora generiamo prospect demo basati sui parametri
            demo_companies = self.generate_demo_companies(provincia, settore)
            
            for company_data in demo_companies:
                prospect = Prospect(
                    ragione_sociale=company_data['nome'],
                    settore=settore,
                    fatturato=company_data.get('fatturato'),
                    dipendenti=company_data.get('dipendenti'),
                    indirizzo=company_data['indirizzo'],
                    provincia=provincia,
                    telefono=company_data.get('telefono'),
                    email=company_data.get('email'),
                    sito_web=company_data.get('sito_web'),
                    fonte='camera_commercio_fvg',
                    data_inserimento=datetime.now(),
                    codice_ateco=company_data.get('ateco'),
                    piva=company_data.get('piva')
                )
                
                prospects.append(prospect)
            
            logging.info(f"✅ Trovati {len(prospects)} prospect da Camera Commercio")
            
        except Exception as e:
            logging.error(f"❌ Errore ricerca Camera Commercio: {e}")
        
        return prospects
    
    def search_linkedin_companies(self, settore: str, regione: str = "Friuli-Venezia Giulia") -> List[Prospect]:
        """Ricerca aziende LinkedIn con estrazione contatti HR"""
        prospects = []
        
        try:
            # LinkedIn Sales Navigator API simulation
            # In produzione userebbe LinkedIn Sales Navigator API
            
            logging.info(f"🔗 Ricerca LinkedIn: {settore} in {regione}")
            
            # Simula ricerca LinkedIn
            linkedin_companies = [
                {
                    'nome': f'Innovativa {settore} FVG S.r.l.',
                    'settore': settore,
                    'dipendenti': 75,
                    'indirizzo': 'Zona Industriale, Udine',
                    'linkedin_url': 'https://linkedin.com/company/innovativa-fvg',
                    'hr_profiles': [
                        {
                            'nome': 'Marco',
                            'cognome': 'Rossi',
                            'ruolo': 'HR Manager',
                            'linkedin': 'https://linkedin.com/in/marco-rossi-hr'
                        }
                    ]
                }
            ]
            
            for company in linkedin_companies:
                # Estrai primo contatto HR
                hr_contact = company['hr_profiles'][0] if company['hr_profiles'] else {}
                
                prospect = Prospect(
                    ragione_sociale=company['nome'],
                    settore=settore,
                    dipendenti=company['dipendenti'],
                    indirizzo=company['indirizzo'],
                    provincia='Udine',  # Default per FVG
                    linkedin_company=company['linkedin_url'],
                    nome_hr=hr_contact.get('nome'),
                    cognome_hr=hr_contact.get('cognome'),
                    linkedin_hr=hr_contact.get('linkedin'),
                    fonte='linkedin',
                    data_inserimento=datetime.now()
                )
                
                prospects.append(prospect)
            
            logging.info(f"✅ Trovati {len(prospects)} prospect da LinkedIn")
            
        except Exception as e:
            logging.error(f"❌ Errore ricerca LinkedIn: {e}")
        
        return prospects
    
    def extract_contact_info(self, website_url: str) -> Dict:
        """Estrazione avanzata informazioni contatto da siti web"""
        contact_info = {
            'emails': [],
            'phones': [],
            'hr_contacts': [],
            'social_links': {}
        }
        
        if not self.driver or not website_url:
            return contact_info
        
        try:
            self.driver.get(website_url)
            time.sleep(3)
            
            # Cerca pagine contatti
            contact_keywords = ['contatti', 'contact', 'chi-siamo', 'about', 'staff', 'team']
            
            for keyword in contact_keywords:
                try:
                    contact_link = self.driver.find_element(
                        By.XPATH, 
                        f"//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{keyword}')]"
                    )
                    contact_link.click()
                    time.sleep(2)
                    break
                except:
                    continue
            
            # Estrai email
            page_source = self.driver.page_source
            emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', page_source)
            
            # Filtra email HR
            hr_emails = [email for email in emails if any(keyword in email.lower() for keyword in ['hr', 'risorse', 'personale', 'recruiting'])]
            
            contact_info['emails'] = list(set(emails))
            contact_info['hr_emails'] = list(set(hr_emails))
            
            # Estrai telefoni
            phones = re.findall(r'(?:\+39\s?)?(?:0\d{1,4}\s?)?[\d\s\-]{6,12}', page_source)
            contact_info['phones'] = list(set(phones))
            
            logging.info(f"✅ Estratte info contatto da {website_url}")
            
        except Exception as e:
            logging.error(f"❌ Errore estrazione contatti da {website_url}: {e}")
        
        return contact_info
    
    def generate_demo_companies(self, provincia: str, settore: str) -> List[Dict]:
        """Genera aziende demo realistiche per FVG"""
        base_companies = {
            'Udine': [
                {'nome': f'{settore} Friulana S.r.l.', 'fatturato': 3200000, 'dipendenti': 78},
                {'nome': f'Nuova {settore} Udine S.p.A.', 'fatturato': 5800000, 'dipendenti': 145},
                {'nome': f'{settore} Innovativa FVG', 'fatturato': 2800000, 'dipendenti': 65}
            ],
            'Pordenone': [
                {'nome': f'{settore} Pordenonese S.r.l.', 'fatturato': 4100000, 'dipendenti': 95},
                {'nome': f'Moderna {settore} PN', 'fatturato': 3600000, 'dipendenti': 82}
            ],
            'Trieste': [
                {'nome': f'{settore} Adriatica S.p.A.', 'fatturato': 6200000, 'dipendenti': 168},
                {'nome': f'Porto {settore} Trieste', 'fatturato': 4800000, 'dipendenti': 112}
            ],
            'Gorizia': [
                {'nome': f'{settore} di Frontiera S.r.l.', 'fatturato': 2900000, 'dipendenti': 71}
            ]
        }
        
        companies = base_companies.get(provincia, [])
        
        # Aggiungi dettagli
        for company in companies:
            company['indirizzo'] = f"Via dell'Industria {company['dipendenti']}, {provincia} (FVG)"
            company['telefono'] = f"04{provincia[:2].upper()}{company['dipendenti']:03d}XXX"
            company['email'] = f"info@{company['nome'].lower().replace(' ', '').replace('.', '')}.it"
            company['sito_web'] = f"https://www.{company['nome'].lower().replace(' ', '').replace('.', '')}.it"
            company['ateco'] = f"{settore[:2]}00{provincia[:2]}"
            company['piva'] = f"0{company['dipendenti']:02d}0000{hash(company['nome']) % 10000:04d}"
        
        return companies
    
    def __del__(self):
        """Cleanup WebDriver"""
        if hasattr(self, 'driver') and self.driver:
            self.driver.quit()

class AdvancedEmailManager:
    """Gestione email avanzata con template e tracking"""
    
    def __init__(self, db_manager: CloudDatabaseManager):
        self.db_manager = db_manager
        self.smtp_server = db_manager.get_config('smtp_server')
        self.smtp_port = int(db_manager.get_config('smtp_port') or 587)
        
        # Credenziali da variabili ambiente
        self.email = os.getenv('ETJCA_EMAIL') or db_manager.get_config('email_account')
        self.password = os.getenv('ETJCA_EMAIL_PASSWORD')
        
        if not self.password:
            logging.warning("⚠️ Password email non configurata nelle variabili ambiente")
    
    def get_email_template(self, tipo: str) -> Dict:
        """Recupera template email dal database"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT oggetto, corpo FROM email_templates 
            WHERE tipo = %s AND attivo = TRUE
            ORDER BY id DESC LIMIT 1
        ''', (tipo,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {'oggetto': result[0], 'corpo': result[1]}
        else:
            return {'oggetto': 'ETJCA - Contatto commerciale', 'corpo': 'Template non trovato'}
    
    def create_personalized_email(self, prospect: Prospect, template_type: str = "prima_email") -> Dict:
        """Crea email personalizzata con dati prospect"""
        template = self.get_email_template(template_type)
        
        # Dati per personalizzazione
        account_data = {
            'nome_account': self.db_manager.get_config('nome_account'),
            'telefono': self.db_manager.get_config('telefono_account'),
            'email': self.db_manager.get_config('email_account')
        }
        
        # Personalizza oggetto
        oggetto = template['oggetto'].format(
            ragione_sociale=prospect.ragione_sociale,
            settore=prospect.settore or 'il vostro settore',
            **account_data
        )
        
        # Personalizza corpo
        corpo = template['corpo'].format(
            nome_hr=prospect.nome_hr or 'Responsabile Risorse Umane',
            cognome_hr=prospect.cognome_hr or '',
            ragione_sociale=prospect.ragione_sociale,
            settore=prospect.settore or 'il vostro settore',
            provincia=prospect.provincia,
            dipendenti=prospect.dipendenti or 'N/A',
            **account_data
        )
        
        return {
            'oggetto': oggetto,
            'corpo': corpo,
            'destinatario': prospect.email_hr,
            'cc': None,
            'bcc': account_data['email']
        }
    
    def send_email(self, prospect: Prospect, template_type: str = "prima_email", allegati: List[str] = None) -> bool:
        """Invio email con tracking avanzato"""
        
        if not prospect.email_hr:
            self.db_manager.log_sistema('WARNING', f'Email HR non disponibile per {prospect.ragione_sociale}', 'EmailManager')
            return False
        
        if not self.password:
            self.db_manager.log_sistema('ERROR', 'Credenziali email non configurate', 'EmailManager')
            return False
        
        try:
            # Crea email personalizzata
            email_data = self.create_personalized_email(prospect, template_type)
            
            # Setup messaggio
            msg = MIMEMultipart('alternative')
            msg['From'] = self.email
            msg['To'] = email_data['destinatario']
            msg['Subject'] = email_data['oggetto']
            
            if email_data.get('cc'):
                msg['Cc'] = email_data['cc']
            
            if email_data.get('bcc'):
                msg['Bcc'] = email_data['bcc']
            
            # Corpo email in HTML e testo
            corpo_testo = email_data['corpo']
            corpo_html = self.convert_to_html(corpo_testo)
            
            msg.attach(MIMEText(corpo_testo, 'plain', 'utf-8'))
            msg.attach(MIMEText(corpo_html, 'html', 'utf-8'))
            
            # Aggiungi allegati
            if allegati:
                for allegato_path in allegati:
                    if os.path.exists(allegato_path):
                        with open(allegato_path, 'rb') as f:
                            allegato = MIMEBase('application', 'octet-stream')
                            allegato.set_payload(f.read())
                            encoders.encode_base64(allegato)
                            allegato.add_header(
                                'Content-Disposition',
                                f'attachment; filename= {os.path.basename(allegato_path)}'
                            )
                            msg.attach(allegato)
            
            # Invio SMTP
            context = ssl.create_default_context()
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls(context=context)
                server.login(self.email, self.password)
                server.send_message(msg)
            
            # Registra attività
            attivita = Attivita(
                id_prospect=prospect.id if hasattr(prospect, 'id') else 0,
                tipo="email",
                data=datetime.now(),
                oggetto=f"Email {template_type} inviata",
                descrizione=f"Email inviata a {prospect.email_hr}\nOggetto: {email_data['oggetto']}",
                esito="inviata",
                prossima_azione="follow_up_telefonico",
                data_prossima_azione=datetime.now() + timedelta(days=3)
            )
            
            # Se prospect ha ID, inserisci attività
            if hasattr(prospect, 'id') and prospect.id:
                self.db_manager.insert_attivita(attivita)
            
            self.db_manager.log_sistema('INFO', f'Email inviata a {prospect.ragione_sociale}', 'EmailManager')
            return True
            
        except Exception as e:
            self.db_manager.log_sistema('ERROR', f'Errore invio email a {prospect.ragione_sociale}: {str(e)}', 'EmailManager')
            logging.error(f"❌ Errore invio email: {e}")
            return False
    
    def convert_to_html(self, testo: str) -> str:
        """Converte testo in HTML formattato"""
        html = testo.replace('\n', '<br>')
        
        # Converte bullet points
        html = re.sub(r'^• (.+), r'<li>\1</li>', html, flags=re.MULTILINE)
        html = re.sub(r'(<li>.*</li>)', r'<ul>\1</ul>', html, flags=re.DOTALL)
        
        # Stile ETJCA
        html_template = f'''
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                {html}
                
                <hr style="margin: 30px 0; border: 1px solid #ddd;">
                
                <div style="text-align: center; color: #666; font-size: 12px;">
                    <img src="https://www.etjca.it/logo.png" alt="ETJCA" style="height: 40px; margin-bottom: 10px;">
                    <p>ETJCA S.p.A. - Agenzia per il Lavoro<br>
                    Via Valassina, 24 - 20159 Milano<br>
                    www.etjca.it | info@etjca.it</p>
                </div>
            </div>
        </body>
        </html>
        '''
        
        return html_template
    
    def schedule_follow_ups(self):
        """Programma follow-up automatici"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        # Trova prospect per follow-up
        giorni_follow_up = self.db_manager.get_config('giorni_follow_up').split(',')
        
        for giorni in giorni_follow_up:
            data_target = datetime.now() - timedelta(days=int(giorni))
            
            cursor.execute('''
                SELECT p.* FROM prospect p
                LEFT JOIN attivita a ON p.id = a.id_prospect 
                WHERE p.stato = 'contattato'
                AND p.data_inserimento::date = %s::date
                AND NOT EXISTS (
                    SELECT 1 FROM attivita a2 
                    WHERE a2.id_prospect = p.id 
                    AND a2.tipo = 'email' 
                    AND a2.data::date = CURRENT_DATE
                )
            ''', (data_target,))
            
            prospects = cursor.fetchall()
            
            for prospect_data in prospects:
                # Crea oggetto Prospect
                prospect = Prospect(*prospect_data[1:])  # Salta l'ID
                prospect.id = prospect_data[0]
                
                # Invia follow-up
                success = self.send_email(prospect, "follow_up_1")
                
                if success:
                    # Aggiorna stato
                    cursor.execute(
                        'UPDATE prospect SET stato = %s WHERE id = %s',
                        ('follow_up_inviato', prospect.id)
                    )
        
        conn.commit()
        conn.close()

class AdvancedReportManager:
    """Gestione report avanzati con export Excel"""
    
    def __init__(self, db_manager: CloudDatabaseManager):
        self.db_manager = db_manager
    
    def generate_comprehensive_report(self) -> Dict:
        """Genera report completo con tutte le metriche"""
        conn = self.db_manager.get_connection()
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'periodo': 'Ultimo mese',
            'metriche_generali': {},
            'prospect_per_settore': {},
            'prospect_per_provincia': {},
            'prospect_per_fonte': {},
            'conversion_funnel': {},
            'attivita_per_tipo': {},
            'performance_email': {},
            'prossime_azioni': []
        }
        
        try:
            # Metriche generali
            query_metriche = '''
                SELECT 
                    COUNT(*) as total_prospects,
                    COUNT(CASE WHEN stato = 'nuovo' THEN 1 END) as nuovi,
                    COUNT(CASE WHEN stato = 'contattato' THEN 1 END) as contattati,
                    COUNT(CASE WHEN stato = 'interessato' THEN 1 END) as interessati,
                    COUNT(CASE WHEN stato = 'appuntamento_fissato' THEN 1 END) as appuntamenti,
                    COUNT(CASE WHEN stato = 'cliente_acquisito' THEN 1 END) as clienti,
                    AVG(fatturato) as fatturato_medio,
                    AVG(dipendenti) as dipendenti_medio
                FROM prospect
                WHERE data_inserimento >= CURRENT_DATE - INTERVAL '30 days'
            '''
            
            result = pd.read_sql_query(query_metriche, conn)
            report['metriche_generali'] = result.iloc[0].to_dict()
            
            # Calcola conversion rate
            total = report['metriche_generali']['total_prospects']
            clienti = report['metriche_generali']['clienti']
            report['metriche_generali']['conversion_rate'] = (clienti / max(total, 1)) * 100
            
            # Prospect per settore
            settori = pd.read_sql_query('''
                SELECT settore, COUNT(*) as count, AVG(fatturato) as fatturato_medio
                FROM prospect 
                WHERE settore IS NOT NULL
                GROUP BY settore 
                ORDER BY count DESC
            ''', conn)
            report['prospect_per_settore'] = settori.to_dict('records')
            
            # Prospect per provincia
            provincie = pd.read_sql_query('''
                SELECT provincia, COUNT(*) as count, 
                       COUNT(CASE WHEN stato = 'cliente_acquisito' THEN 1 END) as clienti
                FROM prospect 
                WHERE provincia IS NOT NULL
                GROUP BY provincia 
                ORDER BY count DESC
            ''', conn)
            report['prospect_per_provincia'] = provincie.to_dict('records')
            
            # Prospect per fonte
            fonti = pd.read_sql_query('''
                SELECT fonte, COUNT(*) as count,
                       COUNT(CASE WHEN stato = 'cliente_acquisito' THEN 1 END) as clienti,
                       (COUNT(CASE WHEN stato = 'cliente_acquisito' THEN 1 END)::float / COUNT(*)::float * 100) as conversion_rate
                FROM prospect 
                WHERE fonte IS NOT NULL
                GROUP BY fonte 
                ORDER BY count DESC
            ''', conn)
            report['prospect_per_fonte'] = fonti.to_dict('records')
            
            # Attività per tipo
            attivita = pd.read_sql_query('''
                SELECT tipo, COUNT(*) as count,
                       COUNT(CASE WHEN esito = 'positivo' THEN 1 END) as positivi
                FROM attivita 
                WHERE data >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY tipo 
                ORDER BY count DESC
            ''', conn)
            report['attivita_per_tipo'] = attivita.to_dict('records')
            
            # Performance email
            email_stats = pd.read_sql_query('''
                SELECT 
                    COUNT(*) as email_inviate,
                    COUNT(CASE WHEN esito = 'aperta' THEN 1 END) as email_aperte,
                    COUNT(CASE WHEN esito = 'risposta' THEN 1 END) as risposte,
                    (COUNT(CASE WHEN esito = 'aperta' THEN 1 END)::float / COUNT(*)::float * 100) as tasso_apertura,
                    (COUNT(CASE WHEN esito = 'risposta' THEN 1 END)::float / COUNT(*)::float * 100) as tasso_risposta
                FROM attivita 
                WHERE tipo = 'email' 
                AND data >= CURRENT_DATE - INTERVAL '30 days'
            ''', conn)
            
            if not email_stats.empty:
                report['performance_email'] = email_stats.iloc[0].to_dict()
            
            # Prossime azioni
            prossime_azioni = pd.read_sql_query('''
                SELECT p.ragione_sociale, a.prossima_azione, a.data_prossima_azione
                FROM attivita a
                JOIN prospect p ON a.id_prospect = p.id
                WHERE a.data_prossima_azione IS NOT NULL
                AND a.data_prossima_azione >= CURRENT_DATE
                ORDER BY a.data_prossima_azione
                LIMIT 20
            ''', conn)
            report['prossime_azioni'] = prossime_azioni.to_dict('records')
            
        except Exception as e:
            logging.error(f"Errore generazione report: {e}")
            report['errore'] = str(e)
        
        finally:
            conn.close()
        
        return report
    
    def export_to_excel(self, report: Dict) -> str:
        """Esporta report in formato Excel avanzato"""
        try:
            # Crea buffer in memoria
            output = io.BytesIO()
            
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # Sheet 1: Metriche generali
                metriche_df = pd.DataFrame([report['metriche_generali']])
                metriche_df.to_excel(writer, sheet_name='Metriche_Generali', index=False)
                
                # Sheet 2: Prospect per settore
                if report['prospect_per_settore']:
                    settori_df = pd.DataFrame(report['prospect_per_settore'])
                    settori_df.to_excel(writer, sheet_name='Per_Settore', index=False)
                
                # Sheet 3: Prospect per provincia
                if report['prospect_per_provincia']:
                    provincie_df = pd.DataFrame(report['prospect_per_provincia'])
                    provincie_df.to_excel(writer, sheet_name='Per_Provincia', index=False)
                
                # Sheet 4: Performance fonti
                if report['prospect_per_fonte']:
                    fonti_df = pd.DataFrame(report['prospect_per_fonte'])
                    fonti_df.to_excel(writer, sheet_name='Per_Fonte', index=False)
                
                # Sheet 5: Attività
                if report['attivita_per_tipo']:
                    attivita_df = pd.DataFrame(report['attivita_per_tipo'])
                    attivita_df.to_excel(writer, sheet_name='Attivita', index=False)
                
                # Sheet 6: Email performance
                if report['performance_email']:
                    email_df = pd.DataFrame([report['performance_email']])
                    email_df.to_excel(writer, sheet_name='Performance_Email', index=False)
                
                # Sheet 7: Prossime azioni
                if report['prossime_azioni']:
                    azioni_df = pd.DataFrame(report['prossime_azioni'])
                    azioni_df.to_excel(writer, sheet_name='Prossime_Azioni', index=False)
            
            # Salva il file
            filename = f"report_etjca_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            
            # In ambiente cloud, salva in storage temporaneo
            temp_path = f"/tmp/{filename}"
            with open(temp_path, 'wb') as f:
                f.write(output.getvalue())
            
            logging.info(f"✅ Report Excel generato: {filename}")
            return temp_path
            
        except Exception as e:
            logging.error(f"❌ Errore export Excel: {e}")
            return None

class CloudLeadAgent:
    """Agente principale cloud per lead generation ETJCA"""
    
    def __init__(self):
        self.db_manager = CloudDatabaseManager()
        self.web_scraper = AdvancedWebScraper(self.db_manager)
        self.email_manager = AdvancedEmailManager(self.db_manager)
        self.report_manager = AdvancedReportManager(self.db_manager)
        
        self.db_manager.log_sistema('INFO', 'Cloud Lead Agent inizializzato', 'CloudLeadAgent')
        logging.info("🚀 ETJCA Cloud Lead Agent inizializzato")
    
    def run_full_cycle(self) -> Dict:
        """Esegue ciclo completo di lead generation"""
        risultati = {
            'timestamp': datetime.now().isoformat(),
            'prospect_trovati': 0,
            'email_inviate': 0,
            'errori': [],
            'dettagli': []
        }
        
        try:
            self.db_manager.log_sistema('INFO', 'Avvio ciclo completo lead generation', 'CloudLeadAgent')
            
            # 1. Ricerca prospect da tutte le fonti
            provincie = self.db_manager.get_config('provincie_target').split(',')
            settori = self.db_manager.get_config('settori_target').split(',')
            
            for provincia in provincie:
                for settore in settori:
                    # Camera di Commercio
                    prospects_cc = self.web_scraper.search_camera_commercio_fvg(settore.strip(), provincia.strip())
                    
                    # LinkedIn
                    prospects_li = self.web_scraper.search_linkedin_companies(settore.strip())
                    
                    # Salva nel database
                    for prospect in prospects_cc + prospects_li:
                        try:
                            prospect_id = self.db_manager.insert_prospect(prospect)
                            risultati['prospect_trovati'] += 1
                            risultati['dettagli'].append(f"Inserito: {prospect.ragione_sociale}")
                        except Exception as e:
                            risultati['errori'].append(f"Errore inserimento {prospect.ragione_sociale}: {str(e)}")
            
            # 2. Invio email ai nuovi prospect
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM prospect 
                WHERE stato = 'nuovo' 
                AND email_hr IS NOT NULL 
                AND data_inserimento::date = CURRENT_DATE
                LIMIT 20
            ''')
            
            new_prospects = cursor.fetchall()
            conn.close()
            
            for prospect_data in new_prospects:
                try:
                    # Crea oggetto Prospect
                    prospect = Prospect(*prospect_data[1:])  # Salta l'ID
                    prospect.id = prospect_data[0]
                    
                    # Invia email
                    if self.email_manager.send_email(prospect, "prima_email"):
                        risultati['email_inviate'] += 1
                        risultati['dettagli'].append(f"Email inviata a: {prospect.ragione_sociale}")
                        
                        # Aggiorna stato
                        conn = self.db_manager.get_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            'UPDATE prospect SET stato = %s WHERE id = %s',
                            ('contattato', prospect.id)
                        )
                        conn.commit()
                        conn.close()
                    
                    # Pausa tra invii
                    time.sleep(2)
                    
                except Exception as e:
                    risultati['errori'].append(f"Errore email {prospect.ragione_sociale}: {str(e)}")
            
            # 3. Follow-up automatici
            self.email_manager.schedule_follow_ups()
            
            # 4. Log risultati
            self.db_manager.log_sistema(
                'INFO', 
                f'Ciclo completato: {risultati["prospect_trovati"]} prospect, {risultati["email_inviate"]} email', 
                'CloudLeadAgent'
            )
            
            risultati['successo'] = True
            
        except Exception as e:
            risultati['errori'].append(f"Errore generale: {str(e)}")
            risultati['successo'] = False
            self.db_manager.log_sistema('ERROR', f'Errore ciclo completo: {str(e)}', 'CloudLeadAgent')
        
        return risultati
    
    def search_prospects_only(self, settore: str = None, provincia: str = None) -> Dict:
        """Solo ricerca prospect"""
        if not settore:
            settori = self.db_manager.get_config('settori_target').split(',')
        else:
            settori = [settore]
        
        if not provincia:
            provincie = self.db_manager.get_config('provincie_target').split(',')
        else:
            provincie = [provincia]
        
        risultati = {'prospect_trovati': 0, 'dettagli': []}
        
        for prov in provincie:
            for sett in settori:
                prospects = self.web_scraper.search_camera_commercio_fvg(sett.strip(), prov.strip())
                
                for prospect in prospects:
                    try:
                        self.db_manager.insert_prospect(prospect)
                        risultati['prospect_trovati'] += 1
                        risultati['dettagli'].append(f"Trovato: {prospect.ragione_sociale}")
                    except Exception as e:
                        logging.error(f"Errore inserimento prospect: {e}")
        
        return risultati
    
    def send_emails_only(self, template_type: str = "prima_email") -> Dict:
        """Solo invio email"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM prospect 
            WHERE stato = 'nuovo' 
            AND email_hr IS NOT NULL 
            LIMIT 10
        ''')
        
        prospects = cursor.fetchall()
        conn.close()
        
        risultati = {'email_inviate': 0, 'dettagli': []}
        
        for prospect_data in prospects:
            try:
                prospect = Prospect(*prospect_data[1:])
                prospect.id = prospect_data[0]
                
                if self.email_manager.send_email(prospect, template_type):
                    risultati['email_inviate'] += 1
                    risultati['dettagli'].append(f"Email inviata: {prospect.ragione_sociale}")
                
                time.sleep(2)
                
            except Exception as e:
                logging.error(f"Errore invio email: {e}")
        
        return risultati
    
    def generate_report_only(self) -> str:
        """Solo generazione report"""
        report = self.report_manager.generate_comprehensive_report()
        excel_path = self.report_manager.export_to_excel(report)
        return excel_path

# Flask Web App per Cloud
app = Flask(__name__)

# Inizializza agente globale
cloud_agent = CloudLeadAgent()

@app.route('/')
def dashboard():
    """Dashboard web principale"""
    return render_template_string("""
    <!DOCTYPE html>
    <html lang="it">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ETJCA Cloud Lead Agent</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'Segoe UI', sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                color: #333;
            }
            .header {
                background: rgba(255,255,255,0.95);
                padding: 1rem 2rem;
                box-shadow: 0 2px 20px rgba(0,0,0,0.1);
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .logo h1 { color: #2c3e50; font-size: 1.8rem; }
            .status {
                background: #27ae60;
                color: white;
                padding: 0.5rem 1rem;
                border-radius: 25px;
                font-size: 0.9rem;
            }
            .container {
                max-width: 1200px;
                margin: 2rem auto;
                padding: 0 2rem;
            }
            .card {
                background: rgba(255,255,255,0.95);
                border-radius: 15px;
                padding: 2rem;
                margin-bottom: 2rem;
                box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            }
            .btn {
                background: linear-gradient(45deg, #3498db, #2980b9);
                color: white;
                border: none;
                padding: 1rem 2rem;
                border-radius: 8px;
                cursor: pointer;
                font-size: 1rem;
                margin: 0.5rem;
                transition: transform 0.3s ease;
            }
            .btn:hover { transform: translateY(-2px); }
            .btn-success { background: linear-gradient(45deg, #27ae60, #229954); }
            .btn-warning { background: linear-gradient(45deg, #f39c12, #d68910); }
            .metrics {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 1rem;
                margin-bottom: 2rem;
            }
            .metric-card {
                background: #f8f9fa;
                padding: 1.5rem;
                border-radius: 10px;
                text-align: center;
                border-left: 4px solid #3498db;
            }
            .metric-number {
                font-size: 2rem;
                font-weight: bold;
                color: #2c3e50;
            }
            .metric-label {
                color: #7f8c8d;
                margin-top: 0.5rem;
            }
            #log { 
                background: #2c3e50; 
                color: #ecf0f1; 
                padding: 1rem; 
                border-radius: 8px; 
                height: 300px; 
                overflow-y: auto; 
                font-family: monospace;
            }
            .loading { display: none; text-align: center; color: #7f8c8d; }
        </style>
    </head>
    <body>
        <div class="header">
            <div class="logo">
                <h1>🚀 ETJCA Cloud Lead Agent</h1>
            </div>
            <div class="status">☁️ Cloud Attivo</div>
        </div>
        
        <div class="container">
            <div class="metrics">
                <div class="metric-card">
                    <div class="metric-number" id="total-prospects">--</div>
                    <div class="metric-label">Prospect Totali</div>
                </div>
                <div class="metric-card">
                    <div class="metric-number" id="emails-sent">--</div>
                    <div class="metric-label">Email Inviate</div>
                </div>
                <div class="metric-card">
                    <div class="metric-number" id="conversion-rate">--</div>
                    <div class="metric-label">Conversion Rate</div>
                </div>
                <div class="metric-card">
                    <div class="metric-number" id="last-update">--</div>
                    <div class="metric-label">Ultimo Aggiornamento</div>
                </div>
            </div>
            
            <div class="card">
                <h2>🎛️ Controlli Cloud Agent</h2>
                <button class="btn btn-success" onclick="runFullCycle()">🚀 Ciclo Completo</button>
                <button class="btn" onclick="searchProspects()">🔍 Ricerca Prospect</button>
                <button class="btn" onclick="sendEmails()">📧 Invia Email</button>
                <button class="btn btn-warning" onclick="generateReport()">📊 Report Excel</button>
                <a href="/manual_prospect" class="btn" style="text-decoration: none; display: inline-block;">📝 Inserisci Prospect</a>
                <button class="btn" onclick="refreshStats()">🔄 Aggiorna</button>
                <div class="loading" id="loading">⏳ Operazione in corso...</div>
            </div>
            
            <div class="card">
                <h2>📋 Log Sistema Cloud</h2>
                <div id="log">
                    <div>[INIT] ETJCA Cloud Lead Agent inizializzato</div>
                    <div>[READY] Sistema pronto per operazioni cloud</div>
                    <div>[INFO] Database PostgreSQL connesso</div>
                    <div>[INFO] Territory: Friuli Venezia Giulia</div>
                </div>
            </div>
            
            <!-- Gestione Prospect -->
            <div class="card">
                <h2>👥 Gestione Prospect</h2>
                <div style="margin-bottom: 1rem;">
                    <input type="text" id="search-prospects" placeholder="🔍 Cerca per ragione sociale..." style="width: 100%; padding: 0.75rem; border: 2px solid #ddd; border-radius: 8px; font-size: 0.9rem;">
                </div>
                <div style="overflow-x: auto;">
                    <table id="prospects-table" style="width: 100%; border-collapse: collapse; margin-top: 1rem;">
                        <thead>
                            <tr style="background: #f8f9fa; border-bottom: 2px solid #dee2e6;">
                                <th style="padding: 0.75rem; text-align: left; font-weight: 600;">Azienda</th>
                                <th style="padding: 0.75rem; text-align: left; font-weight: 600;">Settore</th>
                                <th style="padding: 0.75rem; text-align: left; font-weight: 600;">Provincia</th>
                                <th style="padding: 0.75rem; text-align: left; font-weight: 600;">Stato</th>
                                <th style="padding: 0.75rem; text-align: left; font-weight: 600;">Fonte</th>
                                <th style="padding: 0.75rem; text-align: center; font-weight: 600;">Azioni</th>
                            </tr>
                        </thead>
                        <tbody id="prospects-tbody">
                            <tr>
                                <td colspan="6" style="padding: 2rem; text-align: center; color: #7f8c8d;">
                                    Caricamento prospect...
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                <div style="margin-top: 1rem; text-align: center;">
                    <button class="btn" onclick="loadMoreProspects()">📄 Carica Altri</button>
                    <a href="/manual_prospect" class="btn btn-success" style="text-decoration: none; margin-left: 0.5rem;">➕ Nuovo Prospect</a>
                </div>
            </div>
        </div>

        <script>
            let currentProspects = [];
            let currentPage = 0;
            const pageSize = 20;

            function addLog(message, type = 'info') {
                const log = document.getElementById('log');
                const timestamp = new Date().toLocaleTimeString();
                const entry = document.createElement('div');
                entry.textContent = `[${timestamp}] ${message}`;
                log.insertBefore(entry, log.firstChild);
                
                while (log.children.length > 50) {
                    log.removeChild(log.lastChild);
                }
            }

            function showLoading(show) {
                document.getElementById('loading').style.display = show ? 'block' : 'none';
            }

            async function refreshStats() {
                try {
                    const response = await fetch('/api/stats');
                    const data = await response.json();
                    
                    document.getElementById('total-prospects').textContent = data.total_prospects || 0;
                    document.getElementById('emails-sent').textContent = data.total_emails || 0;
                    document.getElementById('conversion-rate').textContent = data.conversion_rate ? data.conversion_rate.toFixed(1) + '%' : '0%';
                    document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
                    
                    addLog('Statistiche aggiornate dal cloud');
                } catch (error) {
                    addLog('Errore aggiornamento: ' + error, 'error');
                }
            }

            async function refreshProspects() {
                try {
                    const response = await fetch('/api/prospects');
                    const prospects = await response.json();
                    
                    currentProspects = prospects;
                    displayProspects(prospects);
                    
                } catch (error) {
                    addLog('Errore caricamento prospect: ' + error, 'error');
                }
            }

            function displayProspects(prospects) {
                const tbody = document.getElementById('prospects-tbody');
                tbody.innerHTML = '';
                
                if (prospects.length === 0) {
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="6" style="padding: 2rem; text-align: center; color: #7f8c8d;">
                                Nessun prospect trovato. <a href="/manual_prospect">Inserisci il primo prospect</a>
                            </td>
                        </tr>
                    `;
                    return;
                }
                
                prospects.forEach(prospect => {
                    const row = document.createElement('tr');
                    row.style.borderBottom = '1px solid #dee2e6';
                    row.innerHTML = `
                        <td style="padding: 0.75rem;">
                            <div style="font-weight: 600;">${prospect.ragione_sociale}</div>
                            <div style="font-size: 0.8rem; color: #666;">
                                ${prospect.dipendenti ? prospect.dipendenti + ' dip.' : ''} 
                                ${prospect.fatturato ? '• €' + (prospect.fatturato/1000000).toFixed(1) + 'M' : ''}
                            </div>
                        </td>
                        <td style="padding: 0.75rem; color: #666;">${prospect.settore || 'N/A'}</td>
                        <td style="padding: 0.75rem; color: #666;">${prospect.provincia || 'N/A'}</td>
                        <td style="padding: 0.75rem;">
                            <span class="status-badge status-${prospect.stato || 'nuovo'}" style="padding: 0.25rem 0.5rem; border-radius: 12px; font-size: 0.75rem; font-weight: 500;">
                                ${(prospect.stato || 'nuovo').replace('_', ' ')}
                            </span>
                        </td>
                        <td style="padding: 0.75rem; color: #666; font-size: 0.8rem;">${prospect.fonte || 'N/A'}</td>
                        <td style="padding: 0.75rem; text-align: center;">
                            <button onclick="viewProspectDetails(${prospect.id || 0})" style="background: #3498db; color: white; border: none; padding: 0.25rem 0.5rem; border-radius: 4px; cursor: pointer; margin: 0 0.1rem; font-size: 0.75rem;">👁️</button>
                            <button onclick="sendEmailToProspect(${prospect.id || 0})" style="background: #27ae60; color: white; border: none; padding: 0.25rem 0.5rem; border-radius: 4px; cursor: pointer; margin: 0 0.1rem; font-size: 0.75rem;">📧</button>
                            <button onclick="editProspect(${prospect.id || 0})" style="background: #f39c12; color: white; border: none; padding: 0.25rem 0.5rem; border-radius: 4px; cursor: pointer; margin: 0 0.1rem; font-size: 0.75rem;">✏️</button>
                        </td>
                    `;
                    tbody.appendChild(row);
                });

            async function runFullCycle() {
                showLoading(true);
                addLog('🚀 Avvio ciclo completo cloud...');
                
                try {
                    const response = await fetch('/api/run_full_cycle', { method: 'POST' });
                    const result = await response.json();
                    
                    if (result.successo) {
                        addLog(`✅ Ciclo completato: ${result.prospect_trovati} prospect, ${result.email_inviate} email`);
                        refreshStats();
                        refreshProspects();
                    } else {
                        addLog('❌ Errori durante il ciclo: ' + result.errori.join(', '));
                    }
                } catch (error) {
                    addLog('❌ Errore chiamata API: ' + error);
                } finally {
                    showLoading(false);
                }
            }

            async function searchProspects() {
                showLoading(true);
                addLog('🔍 Ricerca prospect in FVG...');
                
                try {
                    const response = await fetch('/api/search_prospects', { method: 'POST' });
                    const result = await response.json();
                    
                    addLog(`✅ Ricerca completata: ${result.prospect_trovati} prospect trovati`);
                    refreshStats();
                    refreshProspects();
                } catch (error) {
                    addLog('❌ Errore ricerca: ' + error);
                } finally {
                    showLoading(false);
                }
            }

            async function sendEmails() {
                showLoading(true);
                addLog('📧 Invio email personalizzate...');
                
                try {
                    const response = await fetch('/api/send_emails', { method: 'POST' });
                    const result = await response.json();
                    
                    addLog(`✅ Email inviate: ${result.email_inviate} messaggi`);
                    refreshStats();
                } catch (error) {
                    addLog('❌ Errore invio email: ' + error);
                } finally {
                    showLoading(false);
                }
            }

            async function generateReport() {
                showLoading(true);
                addLog('📊 Generazione report Excel...');
                
                try {
                    const response = await fetch('/api/generate_report', { method: 'POST' });
                    
                    if (response.ok) {
                        const blob = await response.blob();
                        const url = window.URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.style.display = 'none';
                        a.href = url;
                        a.download = `report_etjca_${new Date().toISOString().split('T')[0]}.xlsx`;
                        document.body.appendChild(a);
                        a.click();
                        window.URL.revokeObjectURL(url);
                        
                        addLog('✅ Report Excel scaricato');
                    } else {
                        addLog('❌ Errore generazione report');
                    }
                } catch (error) {
                    addLog('❌ Errore download: ' + error);
                } finally {
                    showLoading(false);
                }
            }

            // Inizializzazione
            document.addEventListener('DOMContentLoaded', function() {
                addLog('Dashboard cloud caricata');
                refreshStats();
                refreshProspects();
                
                // Auto-refresh ogni 60 secondi
                setInterval(refreshStats, 60000);
            });
        </script>
    </body>
    </html>
    """)
            }

            async function viewProspectDetails(prospectId) {
                try {
                    const response = await fetch(`/api/prospect_details/${prospectId}`);
                    const data = await response.json();
                    
                    if (response.ok) {
                        showProspectModal(data.prospect, data.attivita);
                    } else {
                        addLog('Errore caricamento dettagli: ' + data.error, 'error');
                    }
                } catch (error) {
                    addLog('Errore: ' + error, 'error');
                }
            }

            function showProspectModal(prospect, attivita) {
                const modal = document.createElement('div');
                modal.style.cssText = `
                    position: fixed; top: 0; left: 0; width: 100%; height: 100%; 
                    background: rgba(0,0,0,0.5); z-index: 1000; display: flex; 
                    align-items: center; justify-content: center; padding: 20px;
                `;
                
                modal.innerHTML = `
                    <div style="background: white; border-radius: 15px; padding: 2rem; max-width: 800px; width: 100%; max-height: 90vh; overflow-y: auto;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
                            <h2 style="color: #2c3e50; margin: 0;">📋 ${prospect.ragione_sociale}</h2>
                            <button onclick="this.closest('div').parentElement.remove()" style="background: none; border: none; font-size: 1.5rem; cursor: pointer;">✕</button>
                        </div>
                        
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem;">
                            <div>
                                <h3 style="color: #34495e; margin-bottom: 1rem;">🏢 Dati Azienda</h3>
                                <p><strong>Settore:</strong> ${prospect.settore || 'N/A'}</p>
                                <p><strong>Provincia:</strong> ${prospect.provincia || 'N/A'}</p>
                                <p><strong>Dipendenti:</strong> ${prospect.dipendenti || 'N/A'}</p>
                                <p><strong>Fatturato:</strong> ${prospect.fatturato ? '€' + (prospect.fatturato/1000000).toFixed(1) + 'M' : 'N/A'}</p>
                                <p><strong>Indirizzo:</strong> ${prospect.indirizzo || 'N/A'}</p>
                                <p><strong>Telefono:</strong> ${prospect.telefono || 'N/A'}</p>
                                <p><strong>Email:</strong> ${prospect.email || 'N/A'}</p>
                                <p><strong>Sito web:</strong> ${prospect.sito_web ? `<a href="${prospect.sito_web}" target="_blank">${prospect.sito_web}</a>` : 'N/A'}</p>
                            </div>
                            
                            <div>
                                <h3 style="color: #34495e; margin-bottom: 1rem;">👤 Contatto HR</h3>
                                <p><strong>Nome:</strong> ${prospect.nome_hr || 'N/A'} ${prospect.cognome_hr || ''}</p>
                                <p><strong>Email HR:</strong> ${prospect.email_hr || 'N/A'}</p>
                                <p><strong>LinkedIn:</strong> ${prospect.linkedin_hr ? `<a href="${prospect.linkedin_hr}" target="_blank">Profilo</a>` : 'N/A'}</p>
                                <p><strong>LinkedIn Azienda:</strong> ${prospect.linkedin_company ? `<a href="${prospect.linkedin_company}" target="_blank">Pagina</a>` : 'N/A'}</p>
                                
                                <h3 style="color: #34495e; margin: 1.5rem 0 1rem 0;">⚙️ Gestione</h3>
                                <p><strong>Stato:</strong> <span class="status-badge status-${prospect.stato}">${(prospect.stato || 'nuovo').replace('_', ' ')}</span></p>
                                <p><strong>Priorità:</strong> ${prospect.priorita || 'media'}</p>
                                <p><strong>Fonte:</strong> ${prospect.fonte || 'N/A'}</p>
                                <p><strong>Data inserimento:</strong> ${prospect.data_inserimento ? new Date(prospect.data_inserimento).toLocaleDateString('it-IT') : 'N/A'}</p>
                                <p><strong>Note:</strong> ${prospect.note || 'Nessuna nota'}</p>
                            </div>
                        </div>
                        
                        <div style="margin-top: 2rem;">
                            <h3 style="color: #34495e; margin-bottom: 1rem;">📅 Attività Recenti</h3>
                            <div style="max-height: 200px; overflow-y: auto; border: 1px solid #dee2e6; border-radius: 8px;">
                                ${attivita.length > 0 ? attivita.map(att => `
                                    <div style="padding: 0.75rem; border-bottom: 1px solid #f8f9fa;">
                                        <div style="display: flex; justify-content: space-between; align-items: center;">
                                            <span style="font-weight: 600; color: #2c3e50;">${att.tipo}</span>
                                            <span style="font-size: 0.8rem; color: #666;">${new Date(att.data).toLocaleDateString('it-IT')}</span>
                                        </div>
                                        <div style="margin-top: 0.25rem; color: #666;">${att.oggetto}</div>
                                        ${att.descrizione ? `<div style="margin-top: 0.25rem; font-size: 0.9rem; color: #777;">${att.descrizione}</div>` : ''}
                                    </div>
                                `).join('') : '<div style="padding: 1rem; text-align: center; color: #999;">Nessuna attività registrata</div>'}
                            </div>
                        </div>
                        
                        <div style="margin-top: 2rem; text-align: center;">
                            <button onclick="sendEmailToProspect(${prospect.id})" style="background: #27ae60; color: white; border: none; padding: 0.75rem 1.5rem; border-radius: 8px; cursor: pointer; margin: 0 0.5rem;">📧 Invia Email</button>
                            <button onclick="editProspect(${prospect.id})" style="background: #f39c12; color: white; border: none; padding: 0.75rem 1.5rem; border-radius: 8px; cursor: pointer; margin: 0 0.5rem;">✏️ Modifica</button>
                            <button onclick="this.closest('div').parentElement.remove()" style="background: #95a5a6; color: white; border: none; padding: 0.75rem 1.5rem; border-radius: 8px; cursor: pointer; margin: 0 0.5rem;">❌ Chiudi</button>
                        </div>
                    </div>
                `;
                
                document.body.appendChild(modal);
                
                // Chiudi modal cliccando fuori
                modal.addEventListener('click', function(e) {
                    if (e.target === modal) {
                        modal.remove();
                    }
                });
            }

            async function sendEmailToProspect(prospectId) {
                showLoading(true);
                addLog(`Invio email a prospect ID ${prospectId}...`);
                
                try {
                    const response = await fetch('/api/send_emails', { 
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ prospect_id: prospectId })
                    });
                    const result = await response.json();
                    
                    if (response.ok) {
                        addLog('✅ Email inviata con successo');
                    } else {
                        addLog('❌ Errore invio email: ' + result.error);
                    }
                } catch (error) {
                    addLog('❌ Errore: ' + error);
                } finally {
                    showLoading(false);
                }
            }

            function editProspect(prospectId) {
                // Redirect al form di modifica
                window.location.href = `/manual_prospect?edit=${prospectId}`;
            }

            function loadMoreProspects() {
                currentPage++;
                refreshProspects();
            }

            // Ricerca prospect
            document.getElementById('search-prospects').addEventListener('input', function(e) {
                const searchTerm = e.target.value.toLowerCase();
                if (searchTerm.length === 0) {
                    displayProspects(currentProspects);
                } else {
                    const filtered = currentProspects.filter(p => 
                        p.ragione_sociale.toLowerCase().includes(searchTerm) ||
                        (p.settore && p.settore.toLowerCase().includes(searchTerm)) ||
                        (p.provincia && p.provincia.toLowerCase().includes(searchTerm))
                    );
                    displayProspects(filtered);
                }
            });

            async function runFullCycle() {
                showLoading(true);
                addLog('🚀 Avvio ciclo completo cloud...');
                
                try {
                    const response = await fetch('/api/run_full_cycle', { method: 'POST' });
                    const result = await response.json();
                    
                    if (result.successo) {
                        addLog(`✅ Ciclo completato: ${result.prospect_trovati} prospect, ${result.email_inviate} email`);
                        refreshStats();
                    } else {
                        addLog('❌ Errori durante il ciclo: ' + result.errori.join(', '));
                    }
                } catch (error) {
                    addLog('❌ Errore chiamata API: ' + error);
                } finally {
                    showLoading(false);
                }
            }

            async function searchProspects() {
                showLoading(true);
                addLog('🔍 Ricerca prospect in FVG...');
                
                try {
                    const response = await fetch('/api/search_prospects', { method: 'POST' });
                    const result = await response.json();
                    
                    addLog(`✅ Ricerca completata: ${result.prospect_trovati} prospect trovati`);
                    refreshStats();
                } catch (error) {
                    addLog('❌ Errore ricerca: ' + error);
                } finally {
                    showLoading(false);
                }
            }

            async function sendEmails() {
                showLoading(true);
                addLog('📧 Invio email personalizzate...');
                
                try {
                    const response = await fetch('/api/send_emails', { method: 'POST' });
                    const result = await response.json();
                    
                    addLog(`✅ Email inviate: ${result.email_inviate} messaggi`);
                    refreshStats();
                } catch (error) {
                    addLog('❌ Errore invio email: ' + error);
                } finally {
                    showLoading(false);
                }
            }

            async function generateReport() {
                showLoading(true);
                addLog('📊 Generazione report Excel...');
                
                try {
                    const response = await fetch('/api/generate_report', { method: 'POST' });
                    
                    if (response.ok) {
                        const blob = await response.blob();
                        const url = window.URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.style.display = 'none';
                        a.href = url;
                        a.download = `report_etjca_${new Date().toISOString().split('T')[0]}.xlsx`;
                        document.body.appendChild(a);
                        a.click();
                        window.URL.revokeObjectURL(url);
                        
                        addLog('✅ Report Excel scaricato');
                    } else {
                        addLog('❌ Errore generazione report');
                    }
                } catch (error) {
                    addLog('❌ Errore download: ' + error);
                } finally {
                    showLoading(false);
                }
            }

            // Inizializzazione
            document.addEventListener('DOMContentLoaded', function() {
                addLog('Dashboard cloud caricata');
                refreshStats();
                
                // Auto-refresh ogni 60 secondi
                setInterval(refreshStats, 60000);
            });
        </script>
    </body>
    </html>
    """)

# API Routes
@app.route('/api/stats')
def api_stats():
    """API statistiche"""
    try:
        conn = cloud_agent.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM prospect')
        total_prospects = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM attivita WHERE tipo = %s', ('email',))
        total_emails = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT COUNT(CASE WHEN stato = 'cliente_acquisito' THEN 1 END)::float / 
                   COUNT(*)::float * 100 as conversion_rate
            FROM prospect WHERE stato IS NOT NULL
        ''')
        conversion_result = cursor.fetchone()
        conversion_rate = conversion_result[0] if conversion_result[0] else 0
        
        conn.close()
        
        return jsonify({
            'total_prospects': total_prospects,
            'total_emails': total_emails,
            'conversion_rate': round(conversion_rate, 2),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/run_full_cycle', methods=['POST'])
def api_run_full_cycle():
    """API ciclo completo"""
    try:
        risultati = cloud_agent.run_full_cycle()
        return jsonify(risultati)
    except Exception as e:
        return jsonify({'successo': False, 'errori': [str(e)]}), 500

@app.route('/api/search_prospects', methods=['POST'])
def api_search_prospects():
    """API ricerca prospect"""
    try:
        risultati = cloud_agent.search_prospects_only()
        return jsonify(risultati)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/send_emails', methods=['POST'])
def api_send_emails():
    """API invio email"""
    try:
        risultati = cloud_agent.send_emails_only()
        return jsonify(risultati)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate_report', methods=['POST'])
def api_generate_report():
    """API generazione report"""
    try:
        excel_path = cloud_agent.generate_report_only()
        if excel_path and os.path.exists(excel_path):
            return send_file(
                excel_path,
                as_attachment=True,
                download_name=f"report_etjca_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
        else:
            return jsonify({'error': 'Errore generazione report'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/prospects')
def api_prospects():
    """API lista prospect"""
    try:
        conn = cloud_agent.db_manager.get_connection()
        
        prospects_df = pd.read_sql_query('''
            SELECT ragione_sociale, settore, provincia, stato, fonte, 
                   data_inserimento, dipendenti, fatturato
            FROM prospect 
            ORDER BY data_inserimento DESC 
            LIMIT 50
        ''', conn)
        
        conn.close()
        return jsonify(prospects_df.to_dict('records'))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config')
def api_config():
    """API configurazione"""
    try:
        config = {
            'nome_account': cloud_agent.db_manager.get_config('nome_account'),
            'email_account': cloud_agent.db_manager.get_config('email_account'),
            'provincie_target': cloud_agent.db_manager.get_config('provincie_target'),
            'settori_target': cloud_agent.db_manager.get_config('settori_target'),
            'max_email_giorno': cloud_agent.db_manager.get_config('max_email_giorno')
        }
        return jsonify(config)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Scheduler per automazione
def schedule_daily_tasks():
    """Programma task giornalieri"""
    schedule.every().day.at("08:00").do(cloud_agent.run_full_cycle)
    schedule.every().day.at("14:00").do(cloud_agent.email_manager.schedule_follow_ups)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

# Avvio scheduler in thread separato
scheduler_thread = threading.Thread(target=schedule_daily_tasks, daemon=True)
scheduler_thread.start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    print("=" * 60)
    print("🚀 ETJCA CLOUD LEAD GENERATION AGENT")
    print("=" * 60)
    print(f"🌐 Port: {port}")
    print("🗄️ Database: PostgreSQL Cloud")
    print("📧 Email: SMTP Cloud")
    print("🔍 Web Scraping: Selenium Cloud")
    print("📊 Reports: Excel Export")
    print("⏰ Scheduler: Automazione giornaliera")
    print("🎯 Target: Friuli Venezia Giulia")
    print("=" * 60)
    
    # Avvia Flask app
    app.run(host='0.0.0.0', port=port, debug=False)
