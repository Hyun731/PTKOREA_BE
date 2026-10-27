# Headless LibreOffice renderer: PPTX -> PDF -> PNG pages.
# Used for the "actual PPTX render" preview path (PRD 11, 12). Not a PowerPoint substitute.
FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends libreoffice-impress python3-uno poppler-utils fontconfig \
 && rm -rf /var/lib/apt/lists/*
COPY fonts/ /usr/share/fonts/truetype/ptk/
RUN fc-cache -f && fc-list | grep -i "Pretendard" && fc-list | grep -i "Noto Sans KR"
WORKDIR /work
COPY convert.py /usr/local/bin/convert.py
COPY render.sh /usr/local/bin/render.sh
RUN chmod +x /usr/local/bin/render.sh
ENTRYPOINT ["/usr/local/bin/render.sh"]
