#!/bin/bash
sudo docker run -it \
	--env-file smartrent.env \
	smartrentbridge:latest
