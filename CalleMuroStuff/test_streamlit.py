import streamlit as st

st.title("🚀 Streamlit Test App")
st.write("If you can see this, Streamlit is working correctly!")
st.success("✅ Success! Your browser can display Streamlit content.")

# Simple interactive element
name = st.text_input("Enter your name:")
if name:
    st.write(f"Hello, {name}! 👋")

# Simple chart
import pandas as pd
import numpy as np

chart_data = pd.DataFrame(
    np.random.randn(20, 3),
    columns=['A', 'B', 'C']
)

st.line_chart(chart_data)