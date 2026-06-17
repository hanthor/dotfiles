# tailvm fish completion — source this file or add to your shell rc:
#   tailvm completion fish > ~/.tailvm-completion.fish
#   echo 'source ~/.tailvm-completion.fish' >> ~/.fishrc

# tailvm fish completion
function __tailvm_complete
    tailvm _complete fish "$argv" (math (count (commandline -opc)) + 1)
end
complete -c tailvm -f -a '(__tailvm_complete (commandline -opc))'

