sudo yum install python36 -y
sudo python36 -m ensurepip
sudo yum install git -y
sudo yum install python36-devel.x86_64 -y
sudo yum groupinstall "Development Tools" -y
sudo python36 -m pip install git+git://github.com/saltstack/salt@2018.3#egg=salt
