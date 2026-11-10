from flask import Flask, render_template

app = Flask(__name__)


# Home / Dashboard Route
@app.route("/")
def dashboard():
    return render_template("dashboard.html")


# Job Criteria Route
@app.route("/job-criteria")
def job_criteria():
    return render_template("job_criteria.html")


# Run Flask Application
if __name__ == "__main__":
    app.run(debug=True)
