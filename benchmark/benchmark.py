
from utils.ssh import SSHUtils
from utils.command import command
from secrets import APP_ID, APP_SECRET
from config import API_URL
import time
import re
import uuid


class Benchmark:

    def __init__(self, botname, version, duration, bm_group, bm_subgroup, pre_bm_file, battery_type, bot_type):
        self.pre_bm_file = pre_bm_file
        self.bm_group = bm_group
        self.bm_subgroup = bm_subgroup
        self.botname = botname
        self.duration = duration
        self.version = version
        self.bot_type = bot_type
        self.battery_type = battery_type
        self.ssh = SSHUtils(self.botname)


    def _do_pre_bm(self):
        """executes the pre_bm file on the bot"""
        self.ssh.command('rm ' + self.pre_bm_file)
        self.ssh.put('./' + self.pre_bm_file)
        self.ssh.command('python ' + self.pre_bm_file)

    def _set_version(self, version='daffy'):
        """sets local dts version"""
        command('dts --set-version {}'.format(version), afterCommand="exit\n", afterLineRegex=r' to list commands.') #please bear with that command as it opens a dt shell

    def _sync_time(self):
        """syncs the time on the bot with the time server"""
        self.ssh.command('sudo service ntp stop && sudo ntpd -gq && sudo service ntp start')

    def _record_bags(self, bagname):
        """starts recording the rosbag with the topics  segment_list and lane_pose (latency)"""
        print('Recoreding Bags')
        self._set_version(self.version)
        cmd = 'dts duckiebot demo --demo_name base --duckiebot_name {}'.format(self.botname)
        command(cmd, afterCommand=('sudo mount -t vfat /dev/sda1 /mnt -o uid=1000,gid=1000 ' 
                                ' && rosbag record /{duckiename}/line_detector_node/segment_list /{duckiename}/lane_controller_node/lane_pose /{duckiename}/lane_filter_node/lane_pose /rosout -O /mnt/{bag_name} --duration {duration}'
                                ' && ls -la /mnt && exit').
                                format(duckiename=self.botname, bag_name=bagname, duration=self.duration-60),
                afterLineRegex=r'Set PYTHONPATH to: /home/software/catkin_ws/src:/opt/ros/kinetic/lib/python2.7/dist-packages:/home/software/catkin_ws/src')

    def _start_lane_following(self):
        """ WIP start the lanefollowing"""
        cmd = 'dts duckiebot keyboard_control {} --cli'.format(self.botname)
        print(cmd)
        print("\n\n\n\n\n START LANEFOLLOWING \n\n\n\n\n")
        #command(cmd) TODO start automatic

    def _upload_to_api(self, diagnostics_id, latencies_bag_name):
        """uploads the file to the hw benchmarkapi"""
        cmd = (' sudo mount -t vfat /dev/sda1 /mnt -o uid=1000,gid=1000 '
               ' && curl -X POST "{api_url}/hw_benchmark/files/{id} "'
               ' -F "meta={{\\\"bot_type\\\":\\\"{bot_type}\\\",\\\"battery_type\\\":\\\"{battery_type}\\\",\\\"release\\\":\\\"{release}\\\"}}"'
               ' -H  "accept: application/json" -H  "Content-Type: multipart/form-data" '
               ' -F "sd_card_json=@{sd_speed}" -F "latencies_bag=@{latencies_bag}" '
               ' -F "meta_json=@{meta_json}"').format(
                    api_url= API_URL,
                    id= diagnostics_id,
                    bot_type=self.bot_type,
                    sd_speed='sd_speed.json',
                    latencies_bag='/mnt/{}.bag'.format(latencies_bag_name),
                    release=self.version, 
                    battery_type=self.battery_type,
                    meta_json='meta.json',
               )
        self.ssh.command(cmd)

    def _do_diagnostics(self, latencies_bag_name):
        """starts the diagnostics"""
        self._set_version('daffy')
        cmd = ('docker -H {botname}.local run -it --rm --net=host -v /var/run/docker.sock:/var/run/docker.sock '
                '-e LOG_API_PROTOCOL=https -e LOG_API_HOSTNAME=dashboard.duckietown.org -e LOG_API_VERSION=1.0 '
                '-e LOG_NOTES="{notes}" --name dts-run-diagnostics-system-monitor duckietown/dt-system-monitor:daffy-arm32v7 -- '
                '--target unix:///var/run/docker.sock --type duckiebot --app-id {app_id} '
                '--app-secret {app_secret} --database db_log_default --filter '
                '--group {group} --subgroup {subgroup} --duration {duration}').format(
                    botname=self.botname,
                    notes="called directly, not via dts",
                    group=self.bm_group,
                    subgroup=self.bm_subgroup,
                    duration=self.duration,
                    app_id=APP_ID,
                    app_secret=APP_SECRET)
        
        diagnostic_id = ""
        log_regex = r'v1__{}__{}__{}__\d*'.format(self.bm_group, self.bm_subgroup, self.botname)

        def update_id(line): 
            global diagnostic_id
            diagnostic_id = re.findall(log_regex, line)[0]
            print(diagnostic_id)

        command(cmd, 
                regex=[r'Log ID:\s+' + log_regex, r'\[system-monitor 00h:00m:[3-5]\ds\]', r'\[system-monitor 00h:01m:[2-5]\ds\]'], 
                callback=[update_id, lambda _: self._start_lane_following(), lambda _: self._record_bags(latencies_bag_name)], 
                onlyOnce=[True, True, True])
        return diagnostic_id
                
    def run(self):
        """starts the whole benchmark in correct order"""
        latencies_bag_name = uuid.uuid1()
        self._sync_time()
        self._do_pre_bm()
        start_cmd = 'dts duckiebot keyboard_control {}'.format(self.botname)
        input("Prepare an open keyboard-control using the command:\n\t{}\n\nTHEN Press Enter to continue...".format(start_cmd))
        id = self._do_diagnostics()
        #id = "v1__atags3__python3__watchtower01__1584492001"
        self._upload_to_api(id, latencies_bag_name)
