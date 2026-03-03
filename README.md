this project is currently under construction


so this command -- 

google-chrome --user-data-dir=./user-data opens a wondows that can let you make a profile login and save to a folder 

then this command --

google-chrome   --remote-debugging-port=9222   --user-data-dir=/home/shrey/Desktop/workwolf/user-data   --no-first-run   --no-default-browser-check

let there be a session that you can use for the agent to connect 


then this cli tool (agent-browser)
agent-browser connect 9222

and shabang it works


step -2 

Install / update CLI (editable mode)

uv tool install -e . --force

Clean Reinstall (when things feel cursed)
uv tool uninstall wolfie
rm ~/.local/bin/wolfie  # only if uninstall fails
uv tool install -e .

