from flask import Flask, render_template

app = Flask(__name__)

# Example data - update with your actual agency info
AGENCIES = [
    {
        "name": "NeuroEdge Properties",
        "location": "Windhoek",
        "tagline": "Smart Real Estate Solutions",
        "url": "https://neuroestates.onrender.com/"
    },

    {
        "name": "Windhoek Property Brokers",
        "location": "Windhoek",
        "tagline": "Integrity in Every Deal",
        "url": "https://windhoekpropertybrokersai.onrender.com"
    },
]

@app.route('/')
def home():
    return render_template('index.html', agencies=AGENCIES)

if __name__ == '__main__':
    app.run(port=7000, debug=True)
