FROM gcr.io/cgsdevelopment-1216/docker-nathankw-bcl2fastq:dc0a0db
LABEL maintainer "Nathaniel Watson nathanielwatson@stanfordhealthcare.org"

COPY . /ssub/

RUN pip install --upgrade pip && pip install /ssub

USER root

ENTRYPOINT ["ssub"]
