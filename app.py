import os
import json
import threading
import time
from flask import Flask, request, jsonify, abort, render_template_string, send_file, url_for
from dotenv import load_dotenv

# Azure Communication Services
from azure.communication.messages import NotificationMessagesClient
from azure.communication.messages.models import TextNotificationContent

# OpenAI
from openai import AzureOpenAI

# PDF
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from PyPDF2 import PdfReader, PdfWriter


# ------------------------
# Load Environment
# ------------------------
load_dotenv()
app = Flask(__name__)

endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "https://whatsappmsgrespond.openai.azure.com/")
deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
subscription_key = os.getenv("AZURE_OPENAI_KEY")

logs = []


# ------------------------
# Conversation Manager with Auto-Expiry
# ------------------------
class ConversationManager:
    def __init__(self, expiry_seconds=1800):  # 30 minutes default
        self.conversations = {}
        self.lock = threading.Lock()
        self.expiry_seconds = expiry_seconds

    def get_or_create(self, user_id, bot_factory):
        now = time.time()
        with self.lock:
            # cleanup before returning
            self.cleanup()

            if user_id not in self.conversations:
                self.conversations[user_id] = {
                    "bot": bot_factory(),
                    "last_activity": now
                }
            else:
                self.conversations[user_id]["last_activity"] = now

            return self.conversations[user_id]["bot"]

    def cleanup(self):
        now = time.time()
        expired = [
            user_id for user_id, data in self.conversations.items()
            if now - data["last_activity"] > self.expiry_seconds
        ]
        for user_id in expired:
            del self.conversations[user_id]


conversation_manager = ConversationManager(expiry_seconds=1800)  # 30 min expiry


# ------------------------
# Azure ChatBot Class
# ------------------------
class AzureChatBot:
    def __init__(self, endpoint, api_key, api_version, deployment):
        self.client = AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=api_key,
        )
        self.deployment = deployment
        self.conversation = [{"role": "system", "content": """
        You are Dr. Sahayak, a trusted multilingual AI health assistant for Indian users.  
Your role is to act like a friendly doctor and guide users through their health concerns step by step.  

Rules:
1. Always greet warmly and give emotional support first.  
2. Ask one question at a time. Prefer one-word answers (Yes/No, Mild/Severe, Age number). Only ask for a sentence if needed.  
3. First collect demographic details: Age, Gender, City/Village.  
4. If a user reports a problem, do not diagnose from the first symptom. Ask about other possible symptoms (Yes/No format).  
5. Once enough information is collected:  
   - Diagnose in simple words.  
   - Explain why they may be affected.  
   - Tell them what to do (home care, lifestyle, when to see doctor).  
   - Tell them what not to do.  
   - Provide awareness and prevention tips from Indian health guidelines (MoHFW, ICMR, WHO).  
6. Always keep the tone warm, supportive, and friendly.  
7. Language handling:  
   - If the user speaks in English → reply in English.  
   - If the user speaks in Hindi using English letters (e.g., "mera naam sachin") → reply in colloquial Hindi using English letters.  
   - If the user speaks in Tamil using English letters (e.g., "enoda peru sachin") → reply in colloquial Tamil using English letters.  
   - Match the user’s language style, but always keep answers clear and supportive.  
8. Never prescribe specific medicines. If the issue is serious, advise them to visit a nearby doctor or government hospital.  
        """}]

    def chat(self, user_input: str) -> str:
        self.conversation.append({"role": "user", "content": user_input})
        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=self.conversation,
            max_tokens=512,
            temperature=0.7,
        )
        reply = response.choices[0].message.content
        self.conversation.append({"role": "assistant", "content": reply})
        return reply


# ------------------------
# Message Sender Class
# ------------------------
class MessagesQuickstart:
    def __init__(self):
        self.connection_string = os.getenv("COMMUNICATION_SERVICES_CONNECTION_STRING")
        self.channelRegistrationId = os.getenv("WHATSAPP_CHANNEL_ID")

    def send_text_message(self, to_number: str, text: str):
        messaging_client = NotificationMessagesClient.from_connection_string(self.connection_string)
        text_options = TextNotificationContent(
            channel_registration_id=self.channelRegistrationId,
            to=[to_number],
            content=text,
        )
        message_responses = messaging_client.send(text_options)
        response = message_responses.receipts[0]
        if response is not None:
            msg = f"✅ Sent reply to {response.to}, id={response.message_id}"
            print(msg)
            logs.append(msg)
        else:
            msg = "❌ Failed to send reply"
            print(msg)
            logs.append(msg)


# ------------------------
# Webhook Listener
# ------------------------
@app.route("/eventgrid", methods=["POST"])
def eventgrid_listener():
    try:
        event = request.get_json()
        logs.append(f"📩 Incoming Event: {json.dumps(event)}")

        for e in event:
            event_type = e.get("eventType")

            if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
                validation_code = e["data"]["validationCode"]
                logs.append(f"🔑 Validation request received: {validation_code}")
                return jsonify({"validationResponse": validation_code})

            elif event_type == "Microsoft.Communication.AdvancedMessageReceived":
                data = e.get("data", {})
                from_number = data.get("from")
                message_body = data.get("content", "")

                if not from_number.startswith("+"):
                    from_number = f"+{from_number}"

                msg_log = f"📲 Incoming AdvancedMessage from {from_number}: {message_body}"
                print(msg_log)
                logs.append(msg_log)

                mq = MessagesQuickstart()

                # reuse or create bot per user (with auto-expiry cleanup)
                bot = conversation_manager.get_or_create(
                    from_number,
                    lambda: AzureChatBot(endpoint, subscription_key, api_version, deployment)
                )

                reply = bot.chat(message_body)
                mq.send_text_message(from_number, reply)

        return "", 200

    except Exception as ex:
        err = f"❌ Error in webhook: {str(ex)}"
        print(err)
        logs.append(err)
        abort(400, str(ex))


# ------------------------
# PDF Upload & Merge
# ------------------------
@app.route('/upload', methods=['POST'])
def upload():
    try:
        content = request.get_json()
        print("Received JSON:", content)

        # Extract values
        name = content.get('name', 'N/A')
        age = content.get('age', 'N/A')
        gender = content.get('gender', 'N/A')
        city = content.get('city', 'N/A')
        phone = content.get('phone', 'N/A')
        symptoms = content.get('symptoms', 'N/A')
        recommendation = content.get('recommendation', 'N/A')
        date = content.get('date', 'N/A')
        time = content.get('time', 'N/A')

        input_pdf = "input.pdf"   # base template
        output_pdf = "output.pdf"
        temp_pdf = "temp.pdf"

        # Create overlay PDF
        c = canvas.Canvas(temp_pdf, pagesize=A4)
        c.setFont("Helvetica", 15)
        c.drawString(250, 507, str(name))
        c.drawString(250, 487, str(age))
        c.drawString(250, 467, str(gender))
        c.drawString(250, 447, str(city))
        c.drawString(250, 427, str(phone))
        c.drawString(100, 357, str(symptoms))
        c.drawString(100, 235, str(recommendation))
        c.drawString(100, 155, str(date))
        c.drawString(95, 135, str(time))
        c.save()

        # Merge overlay into template
        reader = PdfReader(input_pdf)
        writer = PdfWriter()
        overlay_reader = PdfReader(temp_pdf)

        for page_num in range(len(reader.pages)):
            page = reader.pages[page_num]
            if page_num == 0:
                overlay_page = overlay_reader.pages[0]
                page.merge_page(overlay_page)
            writer.add_page(page)

        with open(output_pdf, "wb") as f:
            writer.write(f)

        print(f"✅ PDF created successfully: {output_pdf}")

        # Return download button
        return f"""
        <html>
            <head><title>PDF Generated</title></head>
            <body>
                <h2>✅ PDF Generated Successfully!</h2>
                <p>Click the button below to download your file:</p>
                <a href="{url_for('download_pdf')}" download>
                    <button style="padding:10px 20px; font-size:16px; cursor:pointer;">⬇ Download PDF</button>
                </a>
            </body>
        </html>
        """

    except Exception as ex:
        return f"❌ Error: {str(ex)}", 400


@app.route('/download', methods=['GET'])
def download_pdf():
    output_pdf = "output.pdf"
    if not os.path.exists(output_pdf):
        return "❌ No PDF generated yet. Please POST data to /upload first."
    return send_file(output_pdf, as_attachment=True)


# ------------------------
# Logs Page
# ------------------------
@app.route("/logs", methods=["GET"])
def show_logs():
    template = """
    <html>
        <head><title>Webhook Logs</title></head>
        <body>
            <h1>📜 Webhook Logs</h1>
            <ul>
            {% for log in logs %}
                <li>{{ log }}</li>
            {% endfor %}
            </ul>
        </body>
    </html>
    """
    return render_template_string(template, logs=logs)


# ------------------------
# Home
# ------------------------
@app.route("/", methods=["GET"])
def home():
    return "🚀 ACS WhatsApp Webhook & PDF Service is running! Check /logs.", 200


# ------------------------
# Run App
# ------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
