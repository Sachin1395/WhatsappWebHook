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
subscription_key = os.getenv("AZURE_OPENAI_KEY")
logs = []

# ------------------------
# Conversation Manager with Auto-Expiry
# ------------------------
class ConversationManager:
    def __init__(self, expiry_seconds=1800):
        self.conversations = {}
        self.lock = threading.Lock()
        self.expiry_seconds = expiry_seconds

    def get_or_create(self, user_id, bot_factory):
        now = time.time()
        with self.lock:
            self.cleanup()
            if user_id not in self.conversations:
                self.conversations[user_id] = {"bot": bot_factory(), "last_activity": now}
            else:
                self.conversations[user_id]["last_activity"] = now
            return self.conversations[user_id]["bot"]

    def cleanup(self):
        now = time.time()
        expired = [uid for uid, data in self.conversations.items() if now - data["last_activity"] > self.expiry_seconds]
        for uid in expired:
            del self.conversations[uid]

conversation_manager = ConversationManager(expiry_seconds=1800)

# ------------------------
# ChatAssistant
# ------------------------
class ChatAssistant:
    def __init__(self, endpoint=None, api_key=None, api_version="2024-05-01-preview"):
        if not endpoint and not os.getenv("AZURE_OPENAI_ENDPOINT"):
            raise ValueError("Azure OpenAI endpoint must be provided or set in environment variables.")
        if not api_key and not os.getenv("AZURE_OPENAI_KEY"):
            raise ValueError("Azure OpenAI API key must be provided or set in environment variables.")

        self.client = AzureOpenAI(
            azure_endpoint=endpoint or os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=api_key or os.getenv("AZURE_OPENAI_KEY"),
            api_version=api_version
        )

        self.assistant = self.client.beta.assistants.create(
            model="gpt-4o-mini",
            instructions="""
You are Dr. Jeevan, a trusted multilingual AI health assistant for Indian users.

Goal: Guide users step by step to diagnose health conditions strictly using a knowledge base (vector store / file search). Ask one symptom at a time, branch dynamically based on their response, and collect enough information before giving a conclusion.

Core Behavior Rules

Warm Greeting & Demographics eg: Hello! I'm Dr. Jeevan, your friendly AI health assistant. How can I help you today? If you have any health concerns or questions, feel free to share!

Greet the user warmly and reduce anxiety.

Collect demographic details one by one:

Name → {name}

Age → {age} (number)

Gender → {gender} (Male/Female/Other)

City/Village → {location}

Ask one question at a time. Prefer one-word answers (Yes/No, Mild/Severe, number). Use short sentences only if necessary.

Symptom Collection (Dynamic & KB-driven)

Take the user’s first reported symptom → {reported_symptom}.

Internally search vector store / file search to find matching conditions and their related symptoms.

Ask one symptom at a time, starting with the most critical symptom of the top-matching condition.

After each answer, dynamically select the next relevant symptom based on:

Symptoms of the condition from KB

The user’s previous Yes/No answers

Never tell the user which disease you are checking for.

Example Dynamic Flow:

User: “Sudden high fever”

Assistant: “Do you have chills? (Yes/No)”

User: “No”

Assistant: “Do you have body aches? (Yes/No)”

User: “Yes”

Assistant: “Do you have fatigue? (Yes/No)”

And so on…

Once all condition-related symptoms are asked, always ask:
“Do you have any other symptom apart from these?” (Yes/No)

If Yes → dynamically fetch additional symptoms from KB for further questioning.

If No → proceed to diagnosis.

Symptom Matching & Diagnosis

Internally match all collected {user_symptoms} with KB conditions.

Rank conditions by number of matching symptoms.

Diagnose the condition with the highest match.

If multiple conditions tie, present top 2–3, highlighting the most likely.

If no sufficient match, respond politely:
“I do not have enough information in my medical records for this. Please consult a nearby doctor.”

Retrieve Full KB Info

For the diagnosed condition, get from KB / vector store:

{condition}

{description}

{what_to_do}

{what_not_to_do}

{recommended_treatments}

{prevention_tips}

{urgency_level}

Provide Diagnosis & Advice

Respond clearly:

You have been diagnosed with {condition}. This is a {urgency_level} condition. {description}

What to do: {what_to_do}
What not to do: {what_not_to_do}
Recommendations: {recommended_treatments}
Prevention: {prevention_tips}

Keep the tone warm and supportive.

Never prescribe medicines. If serious, advise visiting a nearby doctor/government hospital.

Final Symptom Check

Always ask: “Do you have any other symptom apart from these?”

If Yes → continue symptom questioning (silent symptom collection).

If No → finalize diagnosis.

Language Adaptation

Detect user language {language}:

English → use KB English fields

Hindi (roman letters, e.g., “mera naam sachin”) → use KB Hindi fields

Tamil (roman letters, e.g., “enoda peru sachin”) → use KB Tamil fields

Match user style but keep answers clear and supportive.

Conversation Rules

Ask one question at a time.

Branch dynamically based on symptom responses.

Collect enough symptoms before providing a conclusion.

Include the final check: “Do you have any other symptom apart from these?”

Always strictly use KB for symptom mapping, description, treatment, and prevention.

Variables

{reported_symptom} → initial complaint

{user_symptoms} → collected Yes/No answers

{condition} → diagnosed condition

{description}, {what_to_do}, {what_not_to_do}, {recommended_treatments}, {prevention_tips}, {urgency_level} → retrieved from KB via vector search

{language} → detected user language

Outcome

User is never told which disease is being checked while asking symptoms.

Diagnosis is accurate and strictly KB-driven.

Supports multilingual responses and urgency guidance.

Symptom questioning is dynamic and adaptive per user input.
""",
            tools=[{"type": "file_search"}],
            tool_resources={"file_search": {"vector_store_ids": ["vs_9SoBLT9LEllyAaMeRgJo38ht"]}},
            temperature=0.75,
            top_p=1
        )

        self.thread = self.client.beta.threads.create()

    def chat(self, user_input: str) -> str:
        self.client.beta.threads.messages.create(thread_id=self.thread.id, role="user", content=user_input)
        run = self.client.beta.threads.runs.create(thread_id=self.thread.id, assistant_id=self.assistant.id)

        while run.status in ["queued", "in_progress", "cancelling"]:
            time.sleep(1)
            run = self.client.beta.threads.runs.retrieve(thread_id=self.thread.id, run_id=run.id)

        if run.status == "completed":
            messages = self.client.beta.threads.messages.list(thread_id=self.thread.id, order="desc", limit=1)
            if messages.data and messages.data[0].role == "assistant":
                for block in messages.data[0].content:
                    if block.type == "text":
                        return block.text.value
            return "No assistant reply found."
        elif run.status == "requires_action":
            return "⚠️ Assistant requires further action."
        else:
            return f"❌ Run ended with status: {run.status}"

# ------------------------
# Message Sender
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
                return jsonify({"validationResponse": e["data"]["validationCode"]})
            elif event_type == "Microsoft.Communication.AdvancedMessageReceived":
                data = e.get("data", {})
                from_number = data.get("from")
                message_body = data.get("content", "")

                if not from_number.startswith("+"):
                    from_number = f"+{from_number}"

                logs.append(f"📲 Incoming AdvancedMessage from {from_number}: {message_body}")
                mq = MessagesQuickstart()

                bot = conversation_manager.get_or_create(
                    from_number,
                    lambda: ChatAssistant(endpoint=endpoint, api_key=subscription_key, api_version="2024-05-01-preview")
                )
                reply = bot.chat(message_body)
                mq.send_text_message(from_number, reply)

        return "", 200
    except Exception as ex:
        logs.append(f"❌ Error in webhook: {str(ex)}")
        abort(400, str(ex))

# ------------------------
# PDF Upload & Merge
# ------------------------
@app.route("/upload", methods=["POST"])
def upload():
    try:
        content = request.get_json()
        name = content.get("name", "N/A")
        age = content.get("age", "N/A")
        gender = content.get("gender", "N/A")
        city = content.get("city", "N/A")
        phone = content.get("phone", "N/A")
        symptoms = content.get("symptoms", "N/A")
        recommendation = content.get("recommendation", "N/A")
        date = content.get("date", "N/A")
        time_val = content.get("time", "N/A")

        input_pdf = "input.pdf"
        temp_pdf = "temp.pdf"
        output_pdf = "output.pdf"

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
        c.drawString(95, 135, str(time_val))
        c.save()

        reader = PdfReader(input_pdf)
        writer = PdfWriter()
        overlay_reader = PdfReader(temp_pdf)

        for i, page in enumerate(reader.pages):
            if i == 0:
                page.merge_page(overlay_reader.pages[0])
            writer.add_page(page)

        with open(output_pdf, "wb") as f:
            writer.write(f)

        return f"""
        <html>
            <body>
                <h2>✅ PDF Generated Successfully!</h2>
                <a href="{url_for('download_pdf')}" download>
                    <button style="padding:10px 20px; font-size:16px;">⬇ Download PDF</button>
                </a>
            </body>
        </html>
        """
    except Exception as ex:
        return f"❌ Error: {str(ex)}", 400

@app.route("/download", methods=["GET"])
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





