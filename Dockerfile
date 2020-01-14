ROM nathankw/bcl2fastq2
LABEL maintainer "Nathaniel Watson nathanielwatson@stanfordhealthcare.org"

#INSTALL Python 3.8.1 along with scipy and numpy packages.
RUN curl -O https://www.python.org/ftp/python/3.8.1/Python-3.8.1.tgz \
	&& tar -zxf Python-3.8.1.tgz \
	&& rm Python-3.8.1.tgz \
	&& cd Python-3.8.1 \
	&& ./configure \
	&& make \
	&& make install 

RUN alias python=python3
RUN alias pip=pip3

RUN pip install --upgrade pip && pip install /sssub                                                    
                                                                                                       
USER root                                                                                              
                                                                                                       
ENTRYPOINT ["sssub"]
