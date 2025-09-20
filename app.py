import os
import json
from flask import Flask, request, jsonify, abort, render_template_string
from dotenv import load_dotenv

# Azure Communication Services
from azure.communication.messages import NotificationMessagesClient
from azure.communication.messages.models import TextNotificationContent

# PDF Libraries
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from PyPDF2 import PdfReader, PdfWriter

load_dotenv()
app = Flask(__name__)

# ------------------------
# Global Logs
# ------------------------
logs = []

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
                mq.send_text_message(from_number, f"You said: {message_body}")

        return "", 200

    except Exception as ex:
        err = f"❌ Error in webhook: {str(ex)}"
        print(err)
        logs.append(err)
        abort(400, str(ex))

# ------------------------
# PDF Upload & Merge
# ------------------------
from flask import send_file, url_for

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        content = request.get_json()
        print("Received JSON:", content)

        # Default values if keys are missing
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

        print(f"PDF created successfully: {output_pdf}")

        # Redirect to download page with button
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

    else:
        return "This is the upload page. Send POST with JSON to use it."


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

@app.route("/", methods=["GET"])
def home():
    return "ACS WhatsApp Webhook & PDF Service 🚀. Check /logs or /upload.", 200

# ------------------------
# Run
# ------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

