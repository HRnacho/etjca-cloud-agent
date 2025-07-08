#!/usr/bin/env python3
"""
ETJCA Lead Generation Agent - Versione Fixed per Railway
Corretti tutti gli errori di deployment
"""

import os
import json
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
import re
import time

# Setup logging per Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Import condizionali per evitare errori se mancano
try:
    import psycopg2
    import pandas as pd
    from flask import Flask, render_template_string, jsonify, request, send_file
    HAS_POSTGRES = True
except ImportError as e:
    logging.warning(f"Import error: {e}")
    HAS_POSTGRES = False
    # Fallback imports
    from flask import Flask, jsonify, request

try:
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    import ssl
    HAS_EMAIL = True
except ImportError:
    HAS_EMAIL = False
    logging.warning("Email libraries not available")

# Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'etjca-secret-key-2024')

@dataclass
class Prospect:
    """Modello Prospect semplificato"""
    ragione_sociale: str
    settore: str
    fatturato: Optional[float] = None
    dipendenti: Optional[int] = None
    indirizzo: str = ""
    provincia: str = ""
    telefono: str = ""
    email: str = ""
    sito_web: str = ""
    nome_hr: str = ""
    cognome_hr: str = ""
    email_hr: str = ""
    linkedin_hr: str = ""
    fonte: str = "inserimento_manuale"
    data_inserimento: Optional[datetime] = None
    stato: str = "nuovo"
    priorita: str = "media"
    note: str = ""
    id: Optional[int] = None

class DatabaseManager:
    """Gestione database con fallback graceful"""
    
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
        self.connected = False
        self.init_database()
    
    def get_connection(self):
        """Connessione sicura al database"""
        if not HAS_POSTGRES or not self.db_url:
            raise Exception("Database non disponibile")
        return psycopg2.connect(self.db_url, sslmode='require')
    
    def init_database(self):
        """Inizializza database con gestione errori"""
        if not HAS_POSTGRES or not self.db_url:
            logging.warning("Database PostgreSQL non configurato")
            return False
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Tabella prospect
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
                    fonte VARCHAR(50),
                    data_inserimento TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    stato VARCHAR(50) DEFAULT 'nuovo',
                    priorita VARCHAR(20) DEFAULT 'media',
                    note TEXT
                )
            ''')
            
            # Tabella attivita
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS attivita (
                    id SERIAL PRIMARY KEY,
                    id_prospect INTEGER REFERENCES prospect(id),
                    tipo VARCHAR(50),
                    data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    oggetto VARCHAR(255),
                    descrizione TEXT,
                    esito VARCHAR(100)
                )
            ''')
            
            # Indici
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_prospect_stato ON prospect(stato)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_prospect_provincia ON prospect(provincia)')
            
            conn.commit()
            conn.close()
            
            self.connected = True
            logging.info("✅ Database PostgreSQL inizializzato")
            return True
            
        except Exception as e:
            logging.error(f"❌ Errore database: {e}")
            self.connected = False
            return False
    
    def insert_prospect(self, prospect: Prospect) -> int:
        """Inserisce prospect nel database"""
        if not self.connected:
            raise Exception("Database non connesso")
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO prospect (
                ragione_sociale, settore, fatturato, dipendenti, indirizzo, provincia,
                telefono, email, sito_web, nome_hr, cognome_hr, email_hr,
                linkedin_hr, fonte, stato, priorita, note
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            prospect.ragione_sociale, prospect.settore, prospect.fatturato,
            prospect.dipendenti, prospect.indirizzo, prospect.provincia,
            prospect.telefono, prospect.email, prospect.sito_web,
            prospect.nome_hr, prospect.cognome_hr, prospect.email_hr,
            prospect.linkedin_hr, prospect.fonte, prospect.stato,
            prospect.priorita, prospect.note
        ))
        
        prospect_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        
        logging.info(f"Prospect inserito: {prospect.ragione_sociale}")
        return prospect_id
    
    def get_prospects(self, limit: int = 50) -> List[Dict]:
        """Recupera lista prospect"""
        if not self.connected:
            return []
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, ragione_sociale, settore, provincia, stato, fonte, 
                       dipendenti, fatturato, data_inserimento
                FROM prospect 
                ORDER BY data_inserimento DESC 
                LIMIT %s
            ''', (limit,))
            
            prospects = []
            for row in cursor.fetchall():
                prospects.append({
                    'id': row[0],
                    'ragione_sociale': row[1],
                    'settore': row[2],
                    'provincia': row[3],
                    'stato': row[4],
                    'fonte': row[5],
                    'dipendenti': row[6],
                    'fatturato': row[7],
                    'data_inserimento': row[8].isoformat() if row[8] else None
                })
            
            conn.close()
            return prospects
            
        except Exception as e:
            logging.error(f"Errore get_prospects: {e}")
            return []
    
    def get_stats(self) -> Dict:
        """Recupera statistiche"""
        if not self.connected:
            return {
                'total_prospects': 0,
                'total_emails': 0,
                'conversion_rate': 0
            }
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM prospect')
            total_prospects = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM attivita WHERE tipo = %s', ('email',))
            total_emails = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*) FROM prospect 
                WHERE stato IN ('interessato', 'appuntamento_fissato', 'cliente_acquisito')
            ''')
            interested = cursor.fetchone()[0]
            
            conversion_rate = (interested / max(total_prospects, 1)) * 100
            
            conn.close()
            
            return {
                'total_prospects': total_prospects,
                'total_emails': total_emails,
                'conversion_rate': round(conversion_rate, 2)
            }
            
        except Exception as e:
            logging.error(f"Errore get_stats: {e}")
            return {
                'total_prospects': 0,
                'total_emails': 0,
                'conversion_rate': 0
            }

class EmailManager:
    """Gestione email semplificata"""
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.smtp_server = 'smtp.gmail.com'
        self.smtp_port = 587
        self.email = os.getenv('ETJCA_EMAIL')
        self.password = os.getenv('ETJCA_EMAIL_PASSWORD')
        self.enabled = HAS_EMAIL and self.email and self.password
        
        if not self.enabled:
            logging.warning("Email non configurato - inserire ETJCA_EMAIL e ETJCA_EMAIL_PASSWORD")
    
    def create_email_template(self, prospect: Prospect) -> str:
        """Crea email personalizzata"""
        nome_account = os.getenv('NOME_ACCOUNT', 'Account Manager ETJCA')
        telefono = os.getenv('TELEFONO_ACCOUNT', '+39 XXX XXXXXXX')
        
        template = f"""Gentile {prospect.nome_hr or 'Responsabile HR'} {prospect.cognome_hr or ''},

Mi presento, sono {nome_account} di ETJCA, una delle prime dieci agenzie per il lavoro in Italia con oltre 25 anni di esperienza nel settore delle risorse umane.

Ho notato che {prospect.ragione_sociale} opera con successo nel settore {prospect.settore or 'il vostro settore'} in Friuli Venezia Giulia, e credo che possiamo offrire un valore significativo alla vostra crescita aziendale.

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
✉️ {self.email}
🌐 www.etjca.it

P.S. Allegato trova la nostra brochure con i servizi dedicati alle aziende del territorio."""
        
        return template
    
    def send_email(self, prospect: Prospect) -> bool:
        """Invia email al prospect"""
        if not self.enabled:
            logging.warning("Email non abilitato")
            return False
        
        if not prospect.email_hr:
            logging.warning(f"Email HR non disponibile per {prospect.ragione_sociale}")
            return False
        
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email
            msg['To'] = prospect.email_hr
            msg['Subject'] = f"ETJCA - Partnership per {prospect.ragione_sociale}"
            
            body = self.create_email_template(prospect)
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            context = ssl.create_default_context()
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls(context=context)
                server.login(self.email, self.password)
                server.send_message(msg)
            
            # Registra attività se database disponibile
            if self.db_manager.connected and prospect.id:
                try:
                    conn = self.db_manager.get_connection()
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO attivita (id_prospect, tipo, oggetto, descrizione, esito)
                        VALUES (%s, %s, %s, %s, %s)
                    ''', (
                        prospect.id, 'email', 'Email ETJCA inviata',
                        f'Email inviata a {prospect.email_hr}', 'inviata'
                    ))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    logging.error(f"Errore registrazione attività: {e}")
            
            logging.info(f"Email inviata a {prospect.ragione_sociale}")
            return True
            
        except Exception as e:
            logging.error(f"Errore invio email: {e}")
            return False

# Inizializza componenti
db_manager = DatabaseManager()
email_manager = EmailManager(db_manager)

# Routes Flask
@app.route('/')
def dashboard():
    """Dashboard principale"""
    return render_template_string(DASHBOARD_TEMPLATE)

@app.route('/manual_prospect')
def manual_prospect_form():
    """Form inserimento manuale"""
    return render_template_string(MANUAL_PROSPECT_TEMPLATE)

@app.route('/api/stats')
def api_stats():
    """API statistiche"""
    try:
        stats = db_manager.get_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/prospects')
def api_prospects():
    """API lista prospect"""
    try:
        prospects = db_manager.get_prospects()
        return jsonify(prospects)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/manual_prospect', methods=['POST'])
def api_manual_prospect():
    """API inserimento manuale prospect"""
    try:
        data = request.json
        
        # Validazione
        if not data.get('ragione_sociale'):
            return jsonify({'error': 'Ragione sociale obbligatoria'}), 400
        
        # Crea prospect
        prospect = Prospect(
            ragione_sociale=data['ragione_sociale'].strip(),
            settore=data.get('settore', '').strip(),
            fatturato=int(data['fatturato']) if data.get('fatturato') else None,
            dipendenti=int(data['dipendenti']) if data.get('dipendenti') else None,
            indirizzo=data.get('indirizzo', '').strip(),
            provincia=data.get('provincia', '').strip(),
            telefono=data.get('telefono', '').strip(),
            email=data.get('email', '').strip(),
            sito_web=data.get('sito_web', '').strip(),
            nome_hr=data.get('nome_hr', '').strip(),
            cognome_hr=data.get('cognome_hr', '').strip(),
            email_hr=data.get('email_hr', '').strip(),
            linkedin_hr=data.get('linkedin_hr', '').strip(),
            stato=data.get('stato', 'nuovo'),
            priorita=data.get('priorita', 'media'),
            note=data.get('note', '').strip(),
            data_inserimento=datetime.now()
        )
        
        # Inserisci nel database
        prospect_id = db_manager.insert_prospect(prospect)
        prospect.id = prospect_id
        
        return jsonify({
            'success': True,
            'prospect_id': prospect_id,
            'message': f'Prospect {prospect.ragione_sociale} inserito con successo'
        })
        
    except Exception as e:
        logging.error(f"Errore inserimento prospect: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/send_emails', methods=['POST'])
def api_send_emails():
    """API invio email"""
    try:
        if not email_manager.enabled:
            return jsonify({'error': 'Email non configurato'}), 400
        
        prospects = db_manager.get_prospects(limit=5)
        email_count = 0
        
        for prospect_data in prospects:
            if prospect_data.get('email_hr'):
                prospect = Prospect(
                    id=prospect_data['id'],
                    ragione_sociale=prospect_data['ragione_sociale'],
                    settore=prospect_data.get('settore', ''),
                    email_hr=prospect_data['email_hr']
                )
                
                if email_manager.send_email(prospect):
                    email_count += 1
                
                time.sleep(2)  # Pausa tra invii
        
        return jsonify({
            'success': True,
            'email_inviate': email_count
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    """Health check per Railway"""
    return jsonify({
        'status': 'healthy',
        'database': 'connected' if db_manager.connected else 'disconnected',
        'email': 'configured' if email_manager.enabled else 'not_configured',
        'timestamp': datetime.now().isoformat()
    })

# Template Dashboard
DASHBOARD_TEMPLATE = '''
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
            text-decoration: none;
            display: inline-block;
        }
        .btn:hover { transform: translateY(-2px); }
        .btn-success { background: linear-gradient(45deg, #27ae60, #229954); }
        .btn-warning { background: linear-gradient(45deg, #f39c12, #d68910); }
        .loading { display: none; text-align: center; color: #666; }
        #log { 
            background: #2c3e50; 
            color: #ecf0f1; 
            padding: 1rem; 
            border-radius: 8px; 
            height: 200px; 
            overflow-y: auto; 
            font-family: monospace;
            font-size: 0.9rem;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">
            <h1>🚀 ETJCA Cloud Lead Agent</h1>
        </div>
        <div class="status">☁️ Railway Live</div>
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
        </div>
        
        <div class="card">
            <h2>🎛️ Controlli Agente</h2>
            <a href="/manual_prospect" class="btn btn-success">📝 Inserisci Prospect</a>
            <button class="btn" onclick="sendEmails()">📧 Invia Email</button>
            <button class="btn btn-warning" onclick="generateReport()">📊 Report</button>
            <button class="btn" onclick="refreshStats()">🔄 Aggiorna</button>
            <div class="loading" id="loading">⏳ Operazione in corso...</div>
        </div>
        
        <div class="card">
            <h2>📋 Log Sistema</h2>
            <div id="log">
                <div>[INIT] ETJCA Cloud Agent inizializzato</div>
                <div>[READY] Railway deployment attivo</div>
                <div>[INFO] Database PostgreSQL connesso</div>
                <div>[INFO] Sistema pronto per FVG</div>
            </div>
        </div>
    </div>

    <script>
        function addLog(message) {
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
                
                addLog('Statistiche aggiornate');
            } catch (error) {
                addLog('Errore aggiornamento: ' + error);
            }
        }

        async function sendEmails() {
            showLoading(true);
            addLog('Invio email in corso...');
            
            try {
                const response = await fetch('/api/send_emails', { method: 'POST' });
                const result = await response.json();
                
                if (result.success) {
                    addLog(`Email inviate: ${result.email_inviate} messaggi`);
                    refreshStats();
                } else {
                    addLog('Errore invio email: ' + result.error);
                }
            } catch (error) {
                addLog('Errore: ' + error);
            } finally {
                showLoading(false);
            }
        }

        function generateReport() {
            addLog('Generazione report...');
            alert('Report generato! Funzionalità disponibile nella versione completa.');
        }

        // Inizializzazione
        document.addEventListener('DOMContentLoaded', function() {
            addLog('Dashboard ETJCA caricata');
            refreshStats();
            setInterval(refreshStats, 60000); // Auto-refresh ogni minuto
        });
    </script>
</body>
</html>
'''

# Template Form Inserimento
MANUAL_PROSPECT_TEMPLATE = '''
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Inserimento Prospect - ETJCA</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            color: #333;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: rgba(255,255,255,0.95);
            border-radius: 15px;
            padding: 2rem;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
        }
        .header {
            text-align: center;
            margin-bottom: 2rem;
        }
        .header h1 {
            color: #2c3e50;
            font-size: 1.8rem;
            margin-bottom: 0.5rem;
        }
        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        .form-section {
            background: #f8f9fa;
            padding: 1.5rem;
            border-radius: 10px;
            border-left: 4px solid #3498db;
        }
        .form-section h3 {
            color: #2c3e50;
            font-size: 1.2rem;
            margin-bottom: 1rem;
        }
        .form-group {
            margin-bottom: 1rem;
        }
        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 500;
            color: #555;
        }
        .form-group input,
        .form-group select,
        .form-group textarea {
            width: 100%;
            padding: 0.75rem;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 0.9rem;
            transition: border-color 0.3s ease;
        }
        .form-group input:focus,
        .form-group select:focus,
        .form-group textarea:focus {
            outline: none;
            border-color: #3498db;
        }
        .form-group.required label::after {
            content: " *";
            color: #e74c3c;
        }
        .btn {
            padding: 0.75rem 2rem;
            border: none;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s ease;
            text-decoration: none;
            display: inline-block;
            text-align: center;
        }
        .btn-primary {
            background: linear-gradient(45deg, #3498db, #2980b9);
            color: white;
        }
        .btn-secondary {
            background: #95a5a6;
            color: white;
        }
        .buttons {
            display: flex;
            gap: 1rem;
            justify-content: center;
            margin-top: 2rem;
        }
        .alert {
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
            display: none;
        }
        .alert-success {
            background: #d4edda;
            border: 1px solid #c3e6cb;
            color: #155724;
        }
        .alert-error {
            background: #f8d7da;
            border: 1px solid #f5c6cb;
            color: #721c24;
        }
        .loading {
            display: none;
            text-align: center;
            padding: 1rem;
            color: #666;
        }
        .back-link {
            position: absolute;
            top: 20px;
            left: 20px;
            color: white;
            text-decoration: none;
            font-weight: 500;
            padding: 0.5rem 1rem;
            background: rgba(255, 255, 255, 0.2);
            border-radius: 20px;
            backdrop-filter: blur(10px);
        }
    </style>
</head>
<body>
    <a href="/" class="back-link">← Dashboard</a>
    
    <div class="container">
        <div class="header">
            <h1>📝 Inserimento Prospect ETJCA</h1>
            <p>Aggiungi un nuovo prospect al database</p>
        </div>

        <div class="alert alert-success" id="success-alert"></div>
        <div class="alert alert-error" id="error-alert"></div>
        <div class="loading" id="loading">⏳ Salvataggio...</div>

        <form id="prospect-form">
            <div class="form-grid">
                <div class="form-section">
                    <h3>🏢 Dati Azienda</h3>
                    
                    <div class="form-group required">
                        <label for="ragione_sociale">Ragione Sociale</label>
                        <input type="text" id="ragione_sociale" name="ragione_sociale" required>
                    </div>

                    <div class="form-group required">
                        <label for="settore">Settore</label>
                        <select id="settore" name="settore" required>
                            <option value="">Seleziona settore</option>
                            <option value="Manifatturiero">Manifatturiero</option>
                            <option value="Metalmeccanico">Metalmeccanico</option>
                            <option value="Edilizia">Edilizia</option>
                            <option value="Logistica">Logistica</option>
                            <option value="Commercio">Commercio</option>
                            <option value="Servizi">Servizi</option>
                            <option value="Alimentare">Alimentare</option>
                            <option value="Altro">Altro</option>
                        </select>
                    </div>

                    <div class="form-group required">
                        <label for="provincia">Provincia FVG</label>
                        <select id="provincia" name="provincia" required>
                            <option value="">Seleziona provincia</option>
                            <option value="Udine">Udine</option>
                            <option value="Pordenone">Pordenone</option>
                            <option value="Gorizia">Gorizia</option>
                            <option value="Trieste">Trieste</option>
                        </select>
                    </div>

                    <div class="form-group">
                        <label for="indirizzo">Indirizzo</label>
                        <input type="text" id="indirizzo" name="indirizzo">
                    </div>

                    <div class="form-group">
                        <label for="fatturato">Fatturato Annuo (€)</label>
                        <input type="number" id="fatturato" name="fatturato" min="0">
                    </div>

                    <div class="form-group">
                        <label for="dipendenti">Numero Dipendenti</label>
                        <input type="number" id="dipendenti" name="dipendenti" min="1">
                    </div>
                </div>

                <div class="form-section">
                    <h3>📞 Contatti</h3>
                    
                    <div class="form-group">
                        <label for="telefono">Telefono</label>
                        <input type="tel" id="telefono" name="telefono">
                    </div>

                    <div class="form-group">
                        <label for="email">Email Aziendale</label>
                        <input type="email" id="email" name="email">
                    </div>

                    <div class="form-group">
                        <label for="sito_web">Sito Web</label>
                        <input type="url" id="sito_web" name="sito_web">
                    </div>

                    <div class="form-group">
                        <label for="nome_hr">Nome HR</label>
                        <input type="text" id="nome_hr" name="nome_hr">
                    </div>

                    <div class="form-group">
                        <label for="cognome_hr">Cognome HR</label>
                        <input type="text" id="cognome_hr" name="cognome_hr">
                    </div>

                    <div class="form-group">
                        <label for="email_hr">Email HR</label>
                        <input type="email" id="email_hr" name="email_hr">
                    </div>

                    <div class="form-group">
                        <label for="linkedin_hr">LinkedIn HR</label>
                        <input type="url" id="linkedin_hr" name="linkedin_hr">
                    </div>
                </div>

                <div class="form-section">
                    <h3>⚙️ Gestione</h3>
                    
                    <div class="form-group">
                        <label for="stato">Stato</label>
                        <select id="stato" name="stato">
                            <option value="nuovo">Nuovo</option>
                            <option value="contattato">Contattato</option>
                            <option value="interessato">Interessato</option>
                            <option value="non_interessato">Non Interessato</option>
                        </select>
                    </div>

                    <div class="form-group">
                        <label for="priorita">Priorità</label>
                        <select id="priorita" name="priorita">
                            <option value="bassa">Bassa</option>
                            <option value="media" selected>Media</option>
                            <option value="alta">Alta</option>
                            <option value="urgente">Urgente</option>
                        </select>
                    </div>

                    <div class="form-group">
                        <label for="note">Note</label>
                        <textarea id="note" name="note" rows="4"></textarea>
                    </div>
                </div>
            </div>

            <div class="buttons">
                <button type="submit" class="btn btn-primary">💾 Salva Prospect</button>
                <a href="/" class="btn btn-secondary">❌ Annulla</a>
            </div>
        </form>
    </div>

    <script>
        document.getElementById('prospect-form').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const form = e.target;
            const formData = new FormData(form);
            const data = Object.fromEntries(formData.entries());
            
            document.getElementById('success-alert').style.display = 'none';
            document.getElementById('error-alert').style.display = 'none';
            document.getElementById('loading').style.display = 'block';
            
            try {
                const response = await fetch('/api/manual_prospect', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    document.getElementById('success-alert').textContent = result.message;
                    document.getElementById('success-alert').style.display = 'block';
                    form.reset();
                    window.scrollTo(0, 0);
                    
                    setTimeout(() => {
                        window.location.href = '/';
                    }, 2000);
                } else {
                    document.getElementById('error-alert').textContent = result.error;
                    document.getElementById('error-alert').style.display = 'block';
                    window.scrollTo(0, 0);
                }
                
            } catch (error) {
                document.getElementById('error-alert').textContent = 'Errore di connessione: ' + error.message;
                document.getElementById('error-alert').style.display = 'block';
                window.scrollTo(0, 0);
            } finally {
                document.getElementById('loading').style.display = 'none';
            }
        });
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    
    print("=" * 60)
    print("🚀 ETJCA CLOUD LEAD GENERATION AGENT")
    print("=" * 60)
    print(f"🌐 Port: {port}")
    print(f"🗄️ Database: {'✅ Connected' if db_manager.connected else '❌ Disconnected'}")
    print(f"📧 Email: {'✅ Configured' if email_manager.enabled else '❌ Not configured'}")
    print("🎯 Territory: Friuli Venezia Giulia")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=False)
