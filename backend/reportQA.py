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
        """Initialize the ChatGPT model and chat history"""
        self.api_key = api_key
        self.model = model
        self.messages = [
            {"role": "system", "content": "You are a medical AI assistant answering questions after reviewing diagnostic reports."}
        ]
        self.chat_history = []

    def chat_with_gpt(self, user_message, conversation=False):
        """Talk to GPT with context"""
        try:
            self.messages.append({"role": "user", "content": user_message})
            client = openai.OpenAI(api_key=self.api_key)  # Ensure correct instantiation
            response = client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                temperature=0.7
            )
            reply = response.choices[0].message.content
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

        # Step 1: Process Image
        """
        data = np.load(data_pth)
        slo_fundus_image = data["slo_fundus"]
        """

        slo_fundus_image = imageio.imread(data_pth)

        temp_jpg_path = "output/temp_slo_fundus.png"
        imageio.imwrite(temp_jpg_path, slo_fundus_image)
        segmented_image = segment_optic_disc_cup(temp_jpg_path)
        ratio = calculate_cup_to_disc_ratio(temp_jpg_path)

        # Save segmented image for PDF generation
        segmented_output_path = "output/segmented_image.png"
        imageio.imwrite(segmented_output_path, segmented_image)

        # Step 2: Get Disease Prompt and Clinical Note
        disease_prob = predict_glaucoma(temp_jpg_path)
        disease_class = GlaucomaProb2Text(disease_prob)
        core_prompt = disease_class.promptB()
        core_prompt += f" Network B estimates that the optic cup occupies approximately {ratio:.2f}% of the optic disc area."

        clinical_note = note if note.strip() else "No clinical note provided."
        core_prompt += f"\n\nClinician's note: {clinical_note}"

        os.remove(temp_jpg_path)

        # Step 3: Generate Reports
        expert_reports = {}
        for role in roles:
            expert_prompt = f"{core_prompt}\n\nAs a {role}, please analyze this case from your domain expertise. Only include observations and recommendations relevant to your specialty. Avoid repeating what is not within your scope. Do not mention Network A or B. Write this as part of a professional medical report meant to be integrated with other specialists' insights."
            expert_reports[role] = self.chat_with_gpt(expert_prompt)

        return expert_reports, ratio, segmented_output_path

    def generate_synthesis(self, expert_reports: dict):
        """Generate a director-level synthesis based on all expert reports"""
        combined_reports = "\n\n".join(
            [f"{role} Report:\n{report}" for role, report in expert_reports.items()]
        )
        director_prompt = f"The following are diagnostic reports from multiple medical professionals regarding a suspected case of glaucoma based on a fundus image, CAD analysis, and a clinical note.\n\n{combined_reports}\n\nAs the Director, your role is to synthesize these expert opinions into a final comprehensive diagnostic report. Summarize key agreements, resolve minor disagreements, and generate a cohesive interpretation with diagnostic reasoning and recommendations. Write this as if addressing a clinical team or patient record."

        return self.chat_with_gpt(director_prompt)

    def generate_pdf_report(self, image_path, cup_to_disc_ratio, synthesis_text, output_path="output/diagnostic_report.pdf"):
        """
        Generate a professional PDF report with the segmented image, ratio, and synthesis.
        """
        os.makedirs("output", exist_ok=True)
        pdf = FPDF()
        pdf.add_page()

        # Title
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, "Glaucoma Diagnostic Report", ln=True, align='C')

        # Image
        im = Image.open(image_path)
        rgb_image_path = "output/temp_rgb_image.jpg"
        im.convert("RGB").save(rgb_image_path)
        pdf.ln(10)
        pdf.image(rgb_image_path, x=25, w=160)

        # Caption
        pdf.set_font("Arial", '', 12)
        pdf.ln(5)
        caption = f"Cup-to-Disc Ratio: {cup_to_disc_ratio:.2f}%\nRed = Optic Disc, Green = Optic Cup"
        for line in caption.split('\n'):
            pdf.cell(0, 10, line, ln=True)

        # Synthesis
        pdf.ln(5)
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(0, 10, "Final Diagnostic Summary", ln=True)

        pdf.set_font("Arial", '', 12)
        synthesis_text = replace_unicode_chars(synthesis_text)
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
                
        # Footer
        pdf.ln(10)
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(0, 10, "Generated by Medical AI Assistant", ln=True, align='C')

        pdf.output(output_path)
        os.remove(rgb_image_path)

def read_npz(data_pth):
    data = np.load(data_pth)
    for key in data:
        print(f"{key}: {data[key]}")

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
    # note = "The patient has primary open angle glaucoma - moderate in right eye, severe in left eye. Advanced diffuse thinning in retinal nerve fiber layers of both eyes. Recommended for more aggressive treatment. Mild cataracts in both eyes. No glaucoma medication intolerances."

    roles = [
        "Ophthalmologist", "Optometrist", "Glaucoma Specialist",
        "Primary Care Physician", "Ophthalmic Technician", "Pharmacist"
    ]

    print("Generating specialist reports...\n")
    reports, ratio, segmented_image_path = report_generator.generate_reports(data_pth, note, roles)

    print("\nGenerating final synthesis report...\n")
    summary = report_generator.generate_synthesis(reports)

    print("Final Synthesis Report:\n")
    print(summary)

    print("\nGenerating PDF report...\n")
    report_generator.generate_pdf_report(
        image_path=segmented_image_path,
        cup_to_disc_ratio=ratio,
        synthesis_text=summary,
        output_path="output/final_diagnostic_report.pdf"
    )
    print("PDF saved as final_diagnostic_report.pdf")

    # os.remove(segmented_image_path)

    print("\n--- Chat with the Medical AI (type 'exit' to quit) ---")
    while True:
        user_input = input("You: ")
        if user_input.lower() in ["exit", "quit"]:
            print("Goodbye!")
            break
        response = report_generator.chat_with_gpt(user_input)
        print("AI:", response)
    