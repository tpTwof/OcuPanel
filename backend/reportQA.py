import openai
import numpy as np
import os
import imageio.v2 as imageio
from PIL import Image
from fpdf import FPDF
from classifier import predict_glaucoma
from classifier import GlaucomaProb2Text
from segmenter import segment_optic_disc_cup
from segmenter import calculate_cup_to_disc_ratio

class MedicalReportGenerator:
    def __init__(self, api_key: str, model: str = "gpt-4"):
        """Initialize model parameters"""
        self.api_key = api_key
        self.model = model
        self.system_prompt = {
            "role": "system",
            "content": "You are a medical AI assistant answering questions after reviewing diagnostic reports."
        }
        self.chat_history = []
        self.messages = [self.system_prompt]

    def chat_with_gpt(self, user_message, conversation=False, reset=True):
        """Talk to GPT with optional context reset"""
        try:
            if reset:
                messages = [self.system_prompt, {"role": "user", "content": user_message}]
            else:
                self.messages.append({"role": "user", "content": user_message})
                messages = self.messages

            client = openai.OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7
            )
            reply = response.choices[0].message.content

            if not reset:
                self.messages.append({"role": "assistant", "content": reply})
                
            if (conversation):
                self.chat_history.append({"role": "user", "content": user_message})
                self.chat_history.append({"role": "assistant", "content": reply})

            return reply
        except Exception as e:
            return f"Error: {str(e)}"

    def generate_reports(self, data_pth, note, roles=None):
        """Generate diagnostic reports from multiple medical experts"""
        if roles is None:
            roles = ["Ophthalmologist"]

        slo_fundus_image = imageio.imread(data_pth)
        temp_jpg_path = "output/temp_slo_fundus.png"
        imageio.imwrite(temp_jpg_path, slo_fundus_image)
        segmented_image = segment_optic_disc_cup(temp_jpg_path)
        ratio = calculate_cup_to_disc_ratio(temp_jpg_path)

        segmented_output_path = "output/segmented_image.png"
        imageio.imwrite(segmented_output_path, segmented_image)

        disease_prob = predict_glaucoma(temp_jpg_path)
        disease_class = GlaucomaProb2Text(disease_prob)
        core_prompt = disease_class.promptB()
        core_prompt += f" Network B estimates that the cup-to-disc ratio is approximately {ratio:.2f}."
        clinical_note = note if note.strip() else "No clinical note provided."
        core_prompt += f"\n\nClinician's note: {clinical_note}"

        os.remove(temp_jpg_path)

        expert_reports = {}
        for role in roles:
            expert_prompt = (
                f"{core_prompt}\n\nAs a {role}, please analyze this case from your domain expertise. "
                f"Only include observations and recommendations relevant to your specialty. "
                f"Avoid repeating what is not within your scope. Do not mention Network A or B. "
                f"Write this as part of a professional medical report meant to be integrated with other specialists' insights."
            )
            print(expert_prompt)
            expert_reports[role] = self.chat_with_gpt(expert_prompt, reset=True)

        return expert_reports, ratio, segmented_output_path

    def generate_synthesis(self, expert_reports: dict):
        """Generate a director-level synthesis based on all expert reports"""
        combined_reports = "\n\n".join(
            [f"{role} Report:\n{report}" for role, report in expert_reports.items()]
        )
        director_prompt = (
            f"The following is clinical information regarding a suspected case of glaucoma, including findings from a fundus image, "
            f"computer-aided analysis, and a clinician's note:\n\n{combined_reports}\n\n"
            f"Based on the information above, write a final comprehensive diagnostic report. Summarize the key findings, provide "
            f"diagnostic reasoning, and include appropriate recommendations. Do not reference the sources of the information or mention "
            f"any subreports. The report should be written in a professional, neutral tone suitable for a clinical team or patient record."
        )

        return self.chat_with_gpt(director_prompt, reset=False)

    def generate_pdf_report(self, image_path, cup_to_disc_ratio, synthesis_text, output_path="output/diagnostic_report.pdf"):
        """Generate a professional PDF report"""
        os.makedirs("output", exist_ok=True)
        pdf = FPDF()
        pdf.add_page()

        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, "Glaucoma Diagnostic Report", ln=True, align='C')

        im = Image.open(image_path)
        rgb_image_path = "output/temp_rgb_image.jpg"
        im.convert("RGB").save(rgb_image_path)
        pdf.ln(10)
        pdf.image(rgb_image_path, x=25, w=160)

        pdf.set_font("Arial", '', 12)
        pdf.ln(5)
        caption = f"Cup-to-Disc Ratio: {cup_to_disc_ratio:.2f}%\nRed = Optic Disc, Green = Optic Cup"
        for line in caption.split('\n'):
            pdf.cell(0, 10, line, ln=True)

        pdf.ln(5)
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(0, 10, "Final Diagnostic Summary", ln=True)

        pdf.set_font("Arial", '', 12)
        synthesis_text = replace_unicode_chars(synthesis_text)
        synthesis_text = sanitize_for_latin1(synthesis_text)
        lines = synthesis_text.strip().split('\n')
        for line in lines:
            if line.strip() == "":
                pdf.ln(4)
            else:
                pdf.multi_cell(0, 10, line)
                
        if (len(self.chat_history) > 0):        
            pdf.ln(5)
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(0, 10, "Chat History", ln=True)
                    
            for message in self.chat_history:
                if (message["role"] == "user"):
                    pdf.ln(4)
                    pdf.set_font("Arial", 'B', 12)
                    pdf.cell(0, 10, "You:", ln=True)
                else:
                    pdf.ln(4)
                    pdf.set_font("Arial", 'B', 12)
                    pdf.cell(0, 10, "AI:", ln=True)
                    
                pdf.set_font("Arial", '', 12)
                synthesis_text = replace_unicode_chars(message["content"])
                lines = synthesis_text.strip().split('\n')
                for line in lines:
                    if line.strip() == "":
                        pdf.ln(4)
                    else:
                        pdf.multi_cell(0, 10, line)

        pdf.ln(10)
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(0, 10, "Generated by Medical AI Assistant", ln=True, align='C')

        pdf.output(output_path)
        os.remove(rgb_image_path)

def sanitize_for_latin1(text):
    return text.encode("latin-1", errors="replace").decode("latin-1")

def replace_unicode_chars(text):
    replacements = {
        "—": "-", "–": "-",
        "‘": "'", "’": "'",
        "“": '"', "”": '"',
        "•": "*", "…": "...",
        "€": "EUR", "✓": "v",
        "→": "->", "←": "<-"
    }
    for uni_char, replacement in replacements.items():
        text = text.replace(uni_char, replacement)
    return text

if __name__ == "__main__":
    api_key = os.getenv("OPENAI_API_KEY")
    model = "gpt-4.1"

    report_generator = MedicalReportGenerator(api_key, model)
    data_pth = "data/slo_fundus_00004.jpg"
    note = ""
    """    roles = [
        "Ophthalmologist", "Optometrist", "Glaucoma Specialist",
        "Primary Care Physician", "Ophthalmic Technician", "Pharmacist"
    ] """
    roles = ["Ophthalmologist", "Optometrist", "Glaucoma Specialist", "Ophthalmic Technician"]

    reports, ratio, segmented_image_path = report_generator.generate_reports(data_pth, note, roles)
    summary = report_generator.generate_synthesis(reports)
    print(summary)

    report_generator.generate_pdf_report(
        image_path=segmented_image_path,
        cup_to_disc_ratio=ratio,
        synthesis_text=summary,
        output_path="output/final_diagnostic_report.pdf"
    )
    print("PDF saved as final_diagnostic_report.pdf")

    print("\n--- Chat with the Medical AI (type 'exit' to quit) ---")
    while True:
        user_input = input("You: ")
        if user_input.lower() in ["exit", "quit"]:
            print("Goodbye!")
            break
        response = report_generator.chat_with_gpt(user_input, reset=False)
        print("AI:", response)