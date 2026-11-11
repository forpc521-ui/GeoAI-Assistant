"""Protect React-managed text from automatic browser translation mutations."""
import streamlit as st


def protect_page_translation():
    # Static application-owned code only; never interpolate user input here.
    # Browser translation can replace React text nodes and trigger removeChild
    # errors during reruns. Existing damaged pages still need a full reload.
    st.html('''<script>
const root = document.documentElement;
root.lang = 'zh-CN';
root.setAttribute('translate', 'no');
root.classList.add('notranslate');
if (!document.querySelector('meta[name="google"][content="notranslate"]')) {
  const meta = document.createElement('meta');
  meta.name = 'google'; meta.content = 'notranslate';
  document.head.appendChild(meta);
}
</script>''', unsafe_allow_javascript=True)
