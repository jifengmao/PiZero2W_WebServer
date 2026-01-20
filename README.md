create a file named /etc/systemd/system/zerso2w_webserver.service

modfiy the following 
1) user
2) working folder
3) command linee = python /path/to/zero2w_webserver.py

sudo systemctl daemon-reload

sudo systemctl enable zero2w_weberser.service

sudo systemctl start zero2w_weberser.service

*************************

combined with following command

sudo systemctl status zero2w_weberser.service

sudo systemctl stop zero2w_weberser.service

sudo systemctl restart zero2w_weberser.service
